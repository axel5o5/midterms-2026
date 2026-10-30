"""Record the 2024 replay once and build a static, offline copy of the dashboard for the site.

    uv run python scripts/record_replay.py                 # ~7 min: record, then build
    uv run python scripts/record_replay.py --minutes 6     # replay length (default 6)
    uv run python scripts/record_replay.py --build-only    # rebuild site/replay.html from the saved data

It starts `scripts/live.py --replay-2024` on its own port, reads every snapshot from
/events with its arrival time (plus /book.json once and /history at the end), stops that
server (only the process it started), and writes:

- site/replay-data.json: the snapshots, compacted (the signal log is stored once and each
  snapshot keeps a count into it; floats rounded).
- site/replay.html: generated from src/midterms/live/dashboard.html with mapbook.js inlined
  and a small player that stands in for the server (EventSource and fetch), so the two pages
  never drift apart. Nothing in it touches the network except loading replay-data.json.

The market in the replay is simulated (it follows the model 20 seconds late); the page
says so in a banner that stays on screen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = SITE / "replay-data.json"
PAGE = ROOT / "src" / "midterms" / "live" / "dashboard.html"
MAPJS = ROOT / "src" / "midterms" / "web" / "mapbook.js"
OUT = SITE / "replay.html"


# ---- record ------------------------------------------------------------------------

def _get(url: str, timeout: float = 5.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def record(port: int, minutes: float, tail: float) -> dict:
    base = f"http://127.0.0.1:{port}"
    cmd = [sys.executable, str(ROOT / "scripts" / "live.py"), "--replay-2024", "--minutes", str(minutes),
           "--no-open", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(240):
            if proc.poll() is not None:
                raise SystemExit(f"replay server exited early:\n{proc.stderr.read().decode()[-2000:]}")
            try:
                _get(base + "/state", 1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("replay server did not come up")
        print(f"recording {base} for ~{minutes * 60 + tail:.0f}s")

        frames: list[tuple[float, dict]] = []
        stop_at = time.time() + minutes * 60 + tail
        resp = urllib.request.urlopen(base + "/events", timeout=30)
        buf = b""
        last_note = 0.0
        while time.time() < stop_at:
            line = resp.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                buf = line[6:]
            elif line in (b"\n", b"\r\n") and buf:
                frames.append((time.time(), json.loads(buf)))
                buf = b""
                if time.time() - last_note > 30:
                    last_note = time.time()
                    print(f"  {len(frames)} snapshots, {stop_at - time.time():.0f}s to go", flush=True)
        resp.close()

        book = None
        for _ in range(60):
            book = json.loads(_get(base + "/book.json"))
            if book:
                break
            time.sleep(1)
        history = json.loads(_get(base + "/history"))
        return dict(frames=frames, book=book, history=history)
    finally:
        # only the process group we started
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


# ---- compact -----------------------------------------------------------------------

def _round(o):
    if isinstance(o, float):
        return round(o, 2) if abs(o) > 1e8 else round(o, 4)   # timestamps to 10 ms, the rest to 4 places
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    return o


def compact(rec: dict, every: float) -> dict:
    """Snapshots without their signal log (stored once, oldest first; each snapshot keeps
    `en`, how many log entries existed), thinned to at most one per `every` seconds unless
    something besides the clock changed."""
    log: list[dict] = []
    keys: dict[str, int] = {}
    snaps = []
    last_t, last_sig = -1e18, None
    frames = rec["frames"]
    for i, (at, s) in enumerate(frames):
        evs = s.pop("events", [])
        for e in reversed(evs):          # snapshot lists newest first
            k = json.dumps(e, sort_keys=True)
            if k not in keys:
                keys[k] = len(log)
                log.append(e)
        en = len(log)
        # check: the snapshot's list is the newest-first head of the log
        want = [json.dumps(e, sort_keys=True) for e in evs]
        have = [json.dumps(e, sort_keys=True) for e in reversed(log[max(0, en - len(evs)):en])]
        if want != have:
            raise SystemExit(f"signal log is not append-only at snapshot {i}; can't compact this way")
        s["en"] = en
        s["at"] = at
        sig = json.dumps({k: v for k, v in s.items() if k not in ("now", "at", "compute_ms", "markets", "feeds")}, sort_keys=True) \
            + json.dumps([{k: v for k, v in f.items() if k != "last_check"} for f in s.get("feeds", [])], sort_keys=True)
        if sig != last_sig or at - last_t >= every or i == len(frames) - 1:
            snaps.append(_round(s))
            last_t, last_sig = at, sig
    book = rec["book"] or {}
    return dict(note="2024 presidential count replayed against a SIMULATED market that follows the model 20 s late. "
                     "Not real prices. Recorded with scripts/record_replay.py.",
                recorded=time.strftime("%Y-%m-%d"), snaps=snaps, log=_round(log),
                book=dict(states=book.get("states"), tiles=book.get("tiles"), prefix=book.get("prefix", "PRES"), races=[]))


# ---- build the page -----------------------------------------------------------------

STYLE = """<style>
#kspanel { display: none !important; }
.rbar { flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding-top: 8px; border-top: 1px solid var(--line); }
.rbar .warn { font-size: 12px; font-weight: 700; color: var(--bad); border: 1px solid currentColor; border-radius: 4px; padding: 2px 8px; letter-spacing: 0.02em; }
.rbar button { font: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--ink); cursor: pointer; }
.rbar button.on { background: var(--surface-2); font-weight: 650; }
.rbar .speeds { display: inline-flex; gap: 4px; }
.rbar input[type=range] { flex: 1 1 200px; min-width: 140px; accent-color: var(--ink-2); }
.rbar .pos { font: 12px var(--mono); color: var(--ink-2); min-width: 9.5em; }
.rbar a { font-size: 12px; color: var(--ink-2); }
.rbar .err { color: var(--bad); font-size: 12px; }
#simnote { display: none !important; }            /* the bar's own banner says it */

/* site nav, as on the map and write-up pages (in this page's tokens) */
.site-nav { background: var(--surface); border-bottom: 1px solid var(--line); }
.site-nav-in { max-width: 1500px; margin: 0 auto; padding: 0 20px; display: flex; flex-wrap: wrap; gap: 0 22px; }
.site-nav a { font: 600 14px/1 "Barlow Condensed", "Arial Narrow", system-ui, sans-serif; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2); text-decoration: none; padding: 13px 0 11px; border-bottom: 2px solid transparent; }
.site-nav a:hover { color: var(--ink); }
.site-nav a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--ink); }
.site-nav .ext { color: var(--ink-3); font-weight: 500; }
h1, .panel > .head h2 { font-family: "Barlow Condensed", "Arial Narrow", system-ui, sans-serif; text-transform: uppercase; letter-spacing: 0.03em; }
h1 { font-size: 22px; font-weight: 700; }
.panel > .head h2 { font-size: 15px; font-weight: 700; }

/* one-screen layout: map left, signals and log right, races below */
main { max-width: 1500px; gap: 12px; padding: 12px 20px 28px; grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
       grid-template-areas: "src src" "map side" "races races"; }
main > .sources { grid-area: src; }
main > .tiles { display: none; }
main > .cols { grid-area: side; grid-template-columns: minmax(0, 1fr); gap: 12px; align-content: start; align-items: start; }
main > .cols > .panel { display: block; }
#mappanel { grid-area: map; }
main > section.panel:last-of-type { grid-area: races; }
#signals { max-height: 200px; overflow: auto; }
.events { max-height: 260px; }
#mappanel .mapgrid { grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr); padding: 8px 12px 12px; gap: 12px; }
#map { max-height: 400px; }
#mapside .kv { font-size: 12.5px; }
#mapside ol { display: none; }                     /* pre-election reasoning is for 2026 races, not this replay */
.chip { font-size: 11.5px; padding: 2px 8px; }
.sources { gap: 5px; }
td { padding: 5px 10px; }
.race-name { font-size: 11.5px; }
@media (max-width: 1100px) {
  main { grid-template-columns: minmax(0, 1fr); grid-template-areas: "src" "map" "side" "races"; }
  #mappanel .mapgrid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) { main, .site-nav-in { padding-left: 16px; padding-right: 16px; } }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&display=swap">
"""

NAV = """<nav class="site-nav" aria-label="Site">
  <div class="site-nav-in">
    <a href="./">Map</a>
    <a href="writeup.html">Write-up</a>
    <a href="methodology.html">Methodology</a>
    <a href="replay.html" aria-current="page">Election-night replay</a>
    <a href="https://github.com/axel5o5/midterms-2026">Code &amp; notebooks <span class="ext" aria-hidden="true">↗</span></a>
  </div>
</nav>
"""

BAR = """  <div class="rbar" id="rbar">
    <span class="warn">2024 replay · simulated market, not real prices</span>
    <button id="rplay" type="button" aria-label="Play or pause">Pause</button>
    <span class="speeds" id="rspeed"><button type="button" data-x="1">1×</button><button type="button" data-x="4" class="on">4×</button><button type="button" data-x="16">16×</button></span>
    <button id="rrestart" type="button">Restart</button>
    <input type="range" id="rscrub" min="0" max="1000" value="0" step="1" aria-label="Replay position">
    <span class="pos" id="rpos">loading…</span>
  </div>
"""

# Runs before the dashboard's own script: the clock, fetch and EventSource become the
# recording's. Top-level names from the dashboard script (st, onSnap, pushHistory, lastMap,
# mapDraw) are shared globals, so the player reaches them at run time.
SHIM = r"""<script>
(() => {
  const RealDate = Date, realFetch = window.fetch.bind(window);
  let vnow = null;                                     // replay clock, epoch seconds
  class VDate extends RealDate {
    constructor(...a) { super(...(a.length ? a : [vnow == null ? RealDate.now() : vnow * 1000])); }
    static now() { return vnow == null ? RealDate.now() : vnow * 1000; }
  }
  window.Date = VDate;

  const data = realFetch('replay-data.json').then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const R = { snaps: [], log: [], i: -1, t0: 0, t1: 1, playing: true, speed: 4, es: null, last: 0 };
  const full = (s) => ({ ...s, events: R.log.slice(Math.max(0, s.en - 100), s.en).reverse() });
  const json = (o) => new Response(typeof o === 'string' ? o : JSON.stringify(o), { headers: { 'Content-Type': typeof o === 'string' ? 'text/plain' : 'application/json' } });

  window.fetch = async (url, opts) => {
    const p = typeof url === 'string' ? url : url.url;
    if (p === '/book.json') return json((await data).book);
    if (p === '/history') { await data; return json({}); }
    if (p === '/state') { const d = await data; return json(full(d.snaps[0])); }
    if (p === '/bookmarklet') return json('#');
    if (p.startsWith('/ingest/')) throw new Error('not in the replay');
    return realFetch(url, opts);
  };
  window.EventSource = class { constructor() { R.es = this; this.onmessage = null; this.onerror = null; } close() {} };

  const $ = (id) => document.getElementById(id);
  const fmt = (s) => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  function emit(s) { if (R.es && R.es.onmessage) R.es.onmessage({ data: JSON.stringify(full(s)) }); }
  function ui() {
    $('rplay').textContent = R.playing ? 'Pause' : (vnow >= R.t1 ? 'Play again' : 'Play');
    $('rpos').textContent = `${fmt(vnow - R.t0)} / ${fmt(R.t1 - R.t0)} · ${R.speed}×`;
    if (!R.dragging) $('rscrub').value = Math.round(1000 * (vnow - R.t0) / (R.t1 - R.t0));
    for (const b of $('rspeed').children) b.classList.toggle('on', +b.dataset.x === R.speed);
  }
  function seek(t) {                                   // rebuild the page's state at time t
    vnow = Math.min(R.t1, Math.max(R.t0, t));
    let i = 0; while (i + 1 < R.snaps.length && R.snaps[i + 1].at <= vnow) i++;
    for (const k of Object.keys(st.hist)) delete st.hist[k];
    for (const k of Object.keys(st.prevP)) delete st.prevP[k];
    for (let j = 0; j < i; j++) pushHistory(R.snaps[j]);
    R.i = i; lastMap = 0;
    emit(R.snaps[i]);
    ui();
  }
  function tick(now) {
    const dt = Math.min(0.25, (now - R.last) / 1000); R.last = now;
    if (R.playing && !R.dragging) {
      vnow = Math.min(R.t1, vnow + dt * R.speed);
      while (R.i + 1 < R.snaps.length && R.snaps[R.i + 1].at <= vnow) emit(R.snaps[++R.i]);
      if (vnow >= R.t1) R.playing = false;
      ui();
    }
    requestAnimationFrame(tick);
  }
  data.then((d) => {
    R.snaps = d.snaps; R.log = d.log;
    R.t0 = d.snaps[0].at; R.t1 = d.snaps[d.snaps.length - 1].at;
    const start = () => {
      $('rplay').onclick = () => { if (!R.playing && vnow >= R.t1) seek(R.t0); R.playing = !R.playing; ui(); };
      $('rrestart').onclick = () => { seek(R.t0); R.playing = true; ui(); };
      $('rspeed').onclick = (e) => { const x = +e.target.dataset.x; if (x) { R.speed = x; ui(); } };
      const sc = $('rscrub');
      sc.oninput = () => { R.dragging = true; seek(R.t0 + (R.t1 - R.t0) * sc.value / 1000); };
      sc.onchange = () => { R.dragging = false; ui(); };
      document.addEventListener('keydown', (e) => { if (e.key === ' ' && e.target === document.body) { e.preventDefault(); $('rplay').click(); } });
      vnow = R.t0; R.i = 0;
      setTimeout(() => { seek(R.t0); R.last = performance.now(); requestAnimationFrame(tick); }, 0);
    };
    document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
  }).catch((e) => {
    const go = () => { $('rpos').innerHTML = '<span class="err">Could not load replay-data.json. Serve this folder over http (python3 -m http.server) rather than opening the file directly.</span>'; };
    document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', go) : go();
  });
})();
</script>
"""


def _swap(html: str, old: str, new: str) -> str:
    if html.count(old) != 1:
        raise SystemExit(f"dashboard.html changed: expected exactly one {old!r}")
    return html.replace(old, new)


def build_page() -> None:
    html = PAGE.read_text()
    mapjs = MAPJS.read_text()
    if "</script" in mapjs.lower():
        raise SystemExit("mapbook.js contains </script>; can't inline it")
    if shutil.which("node"):   # optional syntax check; a broken mapbook.js leaves the replay without its map
        chk = subprocess.run(["node", "--check", str(MAPJS)], capture_output=True, text=True)
        if chk.returncode:
            raise SystemExit(f"mapbook.js doesn't parse; fix it first:\n{chk.stderr.strip()[:600]}")
    html = _swap(html, "<title>Election Night Live</title>", "<title>Election Night Replay</title>\n"
                 '<meta name="description" content="The election-night dashboard replaying the 2024 presidential count in seven states, against a simulated market.">')
    html = _swap(html, "</head>", STYLE + SHIM + "</head>")
    html = _swap(html, "<h1>Election night</h1>", "<h1>Election night, replayed</h1>")
    html = _swap(html, "</header>", BAR + "</header>")
    html = _swap(html, "<header>", NAV + "<header>")
    html = _swap(html, '<button data-o="S" class="on">Senate</button>', '<button data-o="S" class="on">States</button>')
    html = _swap(html, '<button data-f="SEN">Senate</button>', '<button data-f="SEN">States</button>')
    # the replay's market is simulated (it follows the model 20 s late); it is not Kalshi data
    html = _swap(html, "const venueName = (v) => v === 'kalshi' ? 'Kalshi' : 'Polymarket';",
                 "const venueName = (v) => v === 'kalshi' ? 'simulated market' : 'Polymarket';")
    html = _swap(html, 'style="background:var(--kalshi)"></i>Kalshi</span>', 'style="background:var(--kalshi)"></i>simulated market</span>')
    html = _swap(html, '<button data-c="kalshi">Kalshi</button>', '<button data-c="kalshi">Simulated market</button>')
    html = _swap(html, '<th class="num">Kalshi</th>', '<th class="num">Sim. market</th>')
    html = _swap(html, "<span>Kalshi</span><b>${r.kalshi", "<span>Sim. market</span><b>${r.kalshi")
    html = _swap(html, "model ${pct(r.p)} · Kalshi ${cents(mid(r.kalshi))} · Poly ${cents(mid(r.polymarket))}", "model ${pct(r.p)} · sim. market ${cents(mid(r.kalshi))}")
    html = _swap(html, "model ${pct(pt[1])} · Kalshi ${cents(pt[2])} · Poly ${cents(pt[3])}", "model ${pct(pt[1])} · sim. market ${cents(pt[2])}")
    html = _swap(html, '<span><i class="key" style="background:var(--poly)"></i>Polymarket</span>', '')
    html = _swap(html, '<button data-c="polymarket">Polymarket</button>', '')
    html = _swap(html, "e.venue === 'kalshi' ? 'K' : 'P'", "e.venue === 'kalshi' ? 'sim' : 'P'")
    html = _swap(html, "<span>Holdout before votes</span>", "<span>Polls before count</span>")
    html = _swap(html, ">Holdout before votes <b>", ">polls before count <b>")
    html = _swap(html, "'starting prices: Holdout before votes'", "'starting prices: final 2024 polling average'")
    html = _swap(html, 'title="Holdout\'s pre-election forecast">Holdout pre<', 'title="The final 2024 polling average, as a probability">Polls pre<')
    html = _swap(html, '<script src="/mapbook.js"></script>', "<script>\n" + mapjs + "\n</script>")
    banner = ("<!-- Generated by scripts/record_replay.py from src/midterms/live/dashboard.html; edit those, not this. -->\n")
    OUT.write_text(_swap(html, "<!doctype html>\n", "<!doctype html>\n" + banner))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} KB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=6.0, help="replay length")
    ap.add_argument("--tail", type=float, default=45.0, help="seconds to keep recording after the count ends")
    ap.add_argument("--port", type=int, default=8768)
    ap.add_argument("--every", type=float, default=1.0, help="keep at most one unchanged snapshot per this many seconds")
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()
    SITE.mkdir(exist_ok=True)
    if not args.build_only:
        rec = record(args.port, args.minutes, args.tail)
        if not rec["frames"]:
            raise SystemExit("no snapshots recorded")
        n_hist = sum(len(v) for v in rec["history"].values())
        out = compact(rec, args.every)
        DATA.write_text(json.dumps(out, separators=(",", ":")))
        span = rec["frames"][-1][0] - rec["frames"][0][0]
        print(f"{len(rec['frames'])} snapshots over {span:.0f}s -> kept {len(out['snaps'])}; "
              f"{len(out['log'])} signal-log entries; engine history {n_hist} points; "
              f"wrote {DATA.relative_to(ROOT)} ({DATA.stat().st_size / 1e6:.2f} MB)")
    build_page()


if __name__ == "__main__":
    main()
