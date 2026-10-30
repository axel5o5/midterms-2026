"""Map shapes for the map pages, as ready-to-draw SVG paths (no map library needed).

States and counties: us-atlas 3.0.1 (built from the Census 2017 cartographic boundary files; already in
an Albers USA projection fit to 975 x 610), downloaded once to data/reference/geo/ from
cdn.jsdelivr.net/npm/us-atlas@3.0.1. TopoJSON arcs are decoded here into one SVG path
per feature.

House: a tile grid, one equal square per district, each state's districts packed into
a block placed on a rough state grid. Several states redrew their lines for 2026, so a
tile layout avoids depending on district shapes that may not be published.
"""

from __future__ import annotations

import json
import math

from .snapshot import ROOT

GEO = ROOT / "data" / "reference" / "geo"
FIPS_TO_ABB = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
               "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
               "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
               "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM",
               "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
               "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
               "54": "WV", "55": "WI", "56": "WY"}

# (row, col) on a 12 x 8 grid, roughly where each state sits
STATE_GRID = {
    "AK": (0, 0), "ME": (0, 11),
    "WI": (1, 6), "VT": (1, 10), "NH": (1, 11),
    "WA": (2, 1), "ID": (2, 2), "MT": (2, 3), "ND": (2, 4), "MN": (2, 5), "IL": (2, 6), "MI": (2, 7), "NY": (2, 9), "MA": (2, 10),
    "OR": (3, 1), "NV": (3, 2), "WY": (3, 3), "SD": (3, 4), "IA": (3, 5), "IN": (3, 6), "OH": (3, 7), "PA": (3, 8), "NJ": (3, 9), "CT": (3, 10), "RI": (3, 11),
    "CA": (4, 1), "UT": (4, 2), "CO": (4, 3), "NE": (4, 4), "MO": (4, 5), "KY": (4, 6), "WV": (4, 7), "VA": (4, 8), "MD": (4, 9), "DE": (4, 10),
    "AZ": (5, 2), "NM": (5, 3), "KS": (5, 4), "AR": (5, 5), "TN": (5, 6), "NC": (5, 7), "SC": (5, 8),
    "OK": (6, 4), "LA": (6, 5), "MS": (6, 6), "AL": (6, 7), "GA": (6, 8),
    "HI": (7, 0), "TX": (7, 4), "FL": (7, 9),
}


def _decode(topo: dict, obj: str, keep=None) -> dict[str, str]:
    """TopoJSON object -> {feature id: SVG path d}."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"

    out = {}
    for g in topo["objects"][obj]["geometries"]:
        fid = str(g.get("id", ""))
        if keep and not keep(fid):
            continue
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]] if g["type"] == "Polygon" else []
        out[fid] = "".join(ring(r) for poly in polys for r in poly)
    return out


def states() -> dict[str, str]:
    """{'IA': path d, ...} in a 975 x 610 frame."""
    topo = json.loads((GEO / "states-albers-10m.json").read_text())
    return {FIPS_TO_ABB[k]: v for k, v in _decode(topo, "states").items() if k in FIPS_TO_ABB}


def counties(state_fips: tuple[str, ...]) -> dict[str, str]:
    topo = json.loads((GEO / "counties-albers-10m.json").read_text())
    return _decode(topo, "counties", keep=lambda f: f[:2] in state_fips)


def bbox(paths: dict[str, str], pad: float = 4) -> list[float]:
    xs, ys = [], []
    for d in paths.values():
        for x, y in (p.split(",") for p in d.replace("M", "L").replace("Z", "").split("L") if p):
            xs.append(float(x))
            ys.append(float(y))
    return [min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad]


def house_tiles(districts: list[str], gap: int = 1) -> dict:
    """{'tiles': {'IA-01': [x, y], ...}, 'labels': {'IA': [x, y]}, 'w': W, 'h': H} in tile units."""
    by_state: dict[str, list[str]] = {}
    for d in sorted(districts):
        by_state.setdefault(d[:2], []).append(d)
    blocks = {}
    for st, ds in by_state.items():
        w = max(1, math.ceil(math.sqrt(len(ds))))
        blocks[st] = (w, math.ceil(len(ds) / w))
    rows, cols = 1 + max(r for r, c in STATE_GRID.values()), 1 + max(c for r, c in STATE_GRID.values())
    col_w = [max([blocks[s][0] for s, (r, c) in STATE_GRID.items() if c == j and s in blocks] or [1]) for j in range(cols)]
    row_h = [max([blocks[s][1] for s, (r, c) in STATE_GRID.items() if r == i and s in blocks] or [1]) + 1 for i in range(rows)]
    x0 = [sum(col_w[:j]) + gap * j for j in range(cols)]
    y0 = [sum(row_h[:i]) + gap * i for i in range(rows)]
    tiles, labels = {}, {}
    for st, ds in by_state.items():
        r, c = STATE_GRID[st]
        w, h = blocks[st]
        bx = x0[c] + (col_w[c] - w) / 2
        by = y0[r] + 1                      # one row for the state label
        labels[st] = [bx + w / 2, y0[r] + 0.6]
        for k, d in enumerate(ds):
            tiles[d] = [bx + k % w, by + k // w]
    return dict(tiles=tiles, labels=labels, w=sum(col_w) + gap * (cols - 1), h=sum(row_h) + gap * (rows - 1))
