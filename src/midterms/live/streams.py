"""Live market prices for election night: a shared quote book fed by
- Polymarket's public market websocket (no key; ~150 updates/s across all midterm
  markets when tested 2026-10-30), reseeded from REST every 60 s as a safety net;
- Kalshi's websocket `ticker` channel when an API key is set, otherwise REST
  batch quotes every 5 s.

Kalshi key (optional, read-only use): create one at kalshi.com/account/profile ->
API Keys, keep the private key in ~/.kalshi/ (chmod 600), and write
    ~/.kalshi/config.json   {"key_id": "...", "private_key": "~/.kalshi/<name>.pem"}
(or export KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH).
The key only signs the websocket handshake (timestamp + "GET" + "/trade-api/ws/v2",
RSA-PSS/SHA-256 or Ed25519, base64; docs.kalshi.com quick_start_websockets).
Nothing here places orders.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from pathlib import Path

import pandas as pd

from . import markets as M

PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
KALSHI_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
KALSHI_REST_EVERY = 5.0
PM_RESEED_EVERY = 60.0


class Book:
    """Latest bid/ask per market id, with the time each last changed."""

    def __init__(self):
        self._q: dict[str, tuple[float, float, float]] = {}
        self._lock = threading.Lock()
        self.version = 0
        self.status: dict[str, dict] = {}   # venue -> {mode, connected, last_msg}

    def set(self, id_: str, bid: float | None, ask: float | None, ts: float | None = None):
        ts = ts or time.time()
        with self._lock:
            old = self._q.get(id_)
            b = bid if bid is not None else (old[0] if old else float("nan"))
            a = ask if ask is not None else (old[1] if old else float("nan"))
            if old is None or old[0] != b or old[1] != a:
                self._q[id_] = (b, a, ts)
                self.version += 1

    def frame(self) -> pd.DataFrame:
        with self._lock:
            return pd.DataFrame([(k, b, a, t) for k, (b, a, t) in self._q.items()], columns=["id", "bid", "ask", "qts"])

    def mark(self, venue: str, **kw):
        self.status.setdefault(venue, {}).update(kw, last_msg=time.time())


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---- Polymarket ---------------------------------------------------------------------

def _pm_apply(book: Book, m: dict):
    et = m.get("event_type")
    ts = (_f(m.get("timestamp")) or time.time() * 1000) / 1000
    if et == "best_bid_ask":
        book.set(m["asset_id"], _f(m.get("best_bid")), _f(m.get("best_ask")), ts)
    elif et == "price_change":
        for c in m.get("price_changes") or []:
            if "best_bid" in c or "best_ask" in c:
                book.set(c["asset_id"], _f(c.get("best_bid")), _f(c.get("best_ask")), ts)
    elif et == "book":
        bids = [_f(x["price"]) for x in m.get("bids") or []]
        asks = [_f(x["price"]) for x in m.get("asks") or []]
        book.set(m["asset_id"], max(bids) if bids else None, min(asks) if asks else None, ts)


async def _pm_loop(book: Book, tokens: list[str], stop: threading.Event):
    import websockets
    while not stop.is_set():
        try:
            async with websockets.connect(PM_WS, max_size=None, ping_interval=None) as ws:
                await ws.send(json.dumps({"assets_ids": tokens, "type": "market", "custom_feature_enabled": True}))
                book.mark("polymarket", mode="websocket", connected=True)
                last_ping = time.time()
                while not stop.is_set():
                    if time.time() - last_ping > 10:
                        await ws.send("PING")
                        last_ping = time.time()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError:
                        continue
                    if raw == "PONG":
                        continue
                    msg = json.loads(raw)
                    for m in msg if isinstance(msg, list) else [msg]:
                        _pm_apply(book, m)
                    book.mark("polymarket", connected=True)
        except Exception as e:  # reconnect after a pause
            book.mark("polymarket", connected=False, error=repr(e)[:200])
            await asyncio.sleep(3)


def _pm_reseed(book: Book, tokens: list[str], stop: threading.Event):
    while not stop.is_set():
        try:
            q = M._polymarket(tokens)
            for r in q.itertuples():
                book.set(r.id, r.bid if r.bid == r.bid else None, r.ask if r.ask == r.ask else None)
        except Exception as e:
            book.mark("polymarket", error=repr(e)[:200])
        stop.wait(PM_RESEED_EVERY)


# ---- Kalshi -------------------------------------------------------------------------

KALSHI_CONFIG = Path("~/.kalshi/config.json").expanduser()


def kalshi_credentials() -> tuple[str, object] | None:
    """Key id and private key from the environment, else ~/.kalshi/config.json
    ({"key_id": ..., "private_key": "~/.kalshi/<name>.pem"}). None if neither is set."""
    key_id, path = os.environ.get("KALSHI_API_KEY_ID"), os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not (key_id and path) and KALSHI_CONFIG.exists():
        cfg = json.loads(KALSHI_CONFIG.read_text())
        key_id, path = cfg.get("key_id"), cfg.get("private_key")
    if not (key_id and path):
        return None
    from cryptography.hazmat.primitives import serialization
    pem = Path(path).expanduser().read_bytes()
    return key_id, serialization.load_pem_private_key(pem, password=None)


def _kalshi_headers(key_id: str, key, path: str = "/trade-api/ws/v2") -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
    ts = str(int(time.time() * 1000))
    msg = (ts + "GET" + path).encode()
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sig = key.sign(msg)
    elif isinstance(key, rsa.RSAPrivateKey):
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                       hashes.SHA256())
    else:
        raise TypeError(f"unsupported Kalshi key type {type(key).__name__}")
    return {"KALSHI-ACCESS-KEY": key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()}


def _k_apply(book: Book, m: dict):
    msg = m.get("msg") or {}
    t = msg.get("market_ticker")
    if not t:
        return
    bid = _f(msg.get("yes_bid_dollars"))
    ask = _f(msg.get("yes_ask_dollars"))
    if bid is None and msg.get("yes_bid") is not None:   # older cent fields
        bid = _f(msg["yes_bid"]) / 100
    if ask is None and msg.get("yes_ask") is not None:
        ask = _f(msg["yes_ask"]) / 100
    book.set(t, bid, ask)


async def _k_loop(book: Book, tickers: list[str], creds, stop: threading.Event):
    import websockets
    key_id, key = creds
    while not stop.is_set():
        try:
            async with websockets.connect(KALSHI_WS, additional_headers=_kalshi_headers(key_id, key),
                                          max_size=None) as ws:
                for i in range(0, len(tickers), 100):
                    await ws.send(json.dumps({"id": i // 100 + 1, "cmd": "subscribe",
                                              "params": {"channels": ["ticker"], "market_tickers": tickers[i:i + 100],
                                                         "send_initial_snapshot": True}}))
                book.mark("kalshi", mode="websocket", connected=True)
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError:
                        continue
                    m = json.loads(raw)
                    if m.get("type") == "error":
                        book.mark("kalshi", error=json.dumps(m)[:200])
                    elif m.get("type") == "ticker":
                        _k_apply(book, m)
                        book.mark("kalshi", connected=True)
        except Exception as e:
            book.mark("kalshi", connected=False, error=repr(e)[:200])
            await asyncio.sleep(5)


def _k_poll(book: Book, tickers: list[str], stop: threading.Event):
    book.mark("kalshi", mode=f"REST every {KALSHI_REST_EVERY:.0f}s", connected=True)
    while not stop.is_set():
        t0 = time.time()
        try:
            q = M._kalshi(tickers)
            for r in q.itertuples():
                book.set(r.id, r.bid or None, r.ask or None)
            book.mark("kalshi", connected=True)
        except Exception as e:
            book.mark("kalshi", connected=False, error=repr(e)[:200])
        stop.wait(max(0.5, KALSHI_REST_EVERY - (time.time() - t0)))


# ---- start --------------------------------------------------------------------------

def _thread(target, *args):
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def start(universe: pd.DataFrame, book: Book, stop: threading.Event, kalshi_ws: bool | None = None) -> None:
    """Start every price feed in background threads. kalshi_ws=None -> websocket if a key is set."""
    tokens = universe.loc[universe["venue"] == "polymarket", "id"].tolist()
    tickers = universe.loc[universe["venue"] == "kalshi", "id"].tolist()
    if tokens:
        _thread(lambda: asyncio.run(_pm_loop(book, tokens, stop)))
        _thread(_pm_reseed, book, tokens, stop)
    if tickers:
        creds = kalshi_credentials() if kalshi_ws is not False else None
        if creds:
            _thread(lambda: asyncio.run(_k_loop(book, tickers, creds, stop)))
            _thread(_k_poll_slow, book, tickers, stop)
        else:
            _thread(_k_poll, book, tickers, stop)


def _k_poll_slow(book: Book, tickers: list[str], stop: threading.Event):
    """Safety net under the Kalshi websocket: a REST pass every minute."""
    while not stop.wait(60):
        try:
            for r in M._kalshi(tickers).itertuples():
                book.set(r.id, r.bid or None, r.ask or None)
        except Exception:
            pass
