"""Build the static Swiss canton map for the web app -> web/lib/swiss-map-paths.ts (run once; output is committed).

    python scripts/build_swiss_map.py <ch-combined.json> [--tolerance 0.6] [--width 400]

Input: `2026/ch-combined.json` from the swiss-maps package (interactivethings/swiss-maps 4.7.0, code BSD-3-Clause),
generated from the generalised administrative boundaries of the Swiss Federal Statistical Office
(Bundesamt für Statistik (BFS), GEOSTAT; base geometry swisstopo). Downloaded once to a scratch folder, never
committed. The script decodes the TopoJSON arcs in pure Python, projects lon/lat with a simple equirectangular
projection scaled by cos(46.8°) (fine at this size), simplifies each shared arc with Douglas-Peucker (so neighbouring
cantons keep identical borders) and writes one SVG path per canton plus the large lakes. No runtime dependency.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "web" / "lib" / "swiss-map-paths.ts"
# BFS canton numbers (geometry ids in the TopoJSON) -> canton code
BFS = {1: "ZH", 2: "BE", 3: "LU", 4: "UR", 5: "SZ", 6: "OW", 7: "NW", 8: "GL", 9: "ZG", 10: "FR", 11: "SO",
       12: "BS", 13: "BL", 14: "SH", 15: "AR", 16: "AI", 17: "SG", 18: "GR", 19: "AG", 20: "TG", 21: "TI",
       22: "VD", 23: "VS", 24: "NE", 25: "GE", 26: "JU"}
LAT0 = math.radians(46.8)


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker; endpoints are kept, so shared arc ends stay shared."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / n
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring(arc_ids: list[int], arcs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in arc_ids:
        seg = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(seg if not pts else seg[1:])
    return pts


def polygons(geom: dict) -> list[list[list[int]]]:
    if geom["type"] == "Polygon":
        return [geom["arcs"]]
    if geom["type"] == "MultiPolygon":
        return geom["arcs"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topojson", type=Path)
    ap.add_argument("--tolerance", type=float, default=0.6, help="simplification tolerance in output pixels")
    ap.add_argument("--width", type=float, default=400.0)
    ap.add_argument("--min-lake-area", type=float, default=40.0, help="drop lakes smaller than this (px^2)")
    a = ap.parse_args(argv)
    topo = json.loads(a.topojson.read_text(encoding="utf-8"))
    raw = decode_arcs(topo)

    proj = [[(lon * math.cos(LAT0), -lat) for lon, lat in arc] for arc in raw]
    xs = [p[0] for arc in proj for p in arc]
    ys = [p[1] for arc in proj for p in arc]
    x0, y0 = min(xs), min(ys)
    k = a.width / (max(xs) - x0)
    height = round((max(ys) - y0) * k, 1)
    px = [[((x - x0) * k, (y - y0) * k) for x, y in arc] for arc in proj]
    simple = [dp(arc, a.tolerance) for arc in px]

    def path_d(geom: dict) -> tuple[str, float]:
        parts, area = [], 0.0
        for poly in polygons(geom):
            for r_i, r in enumerate(poly):
                pts = ring(r, simple)
                if len(pts) < 3:
                    continue
                s = 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))
                area += abs(s) if r_i == 0 else -abs(s)
                parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        return "".join(parts), area

    cantons = {}
    for g in topo["objects"]["cantons"]["geometries"]:
        code = BFS[int(g["id"])]
        d, _ = path_d(g)
        cantons[code] = d
    lakes = []
    for g in topo["objects"]["lakes"]["geometries"]:
        d, area = path_d(g)
        if d and area >= a.min_lake_area:
            lakes.append(d)
    assert len(cantons) == 26, sorted(cantons)

    body = [
        "// GENERATED by scripts/build_swiss_map.py from swiss-maps 4.7.0 (2026/ch-combined.json). Do not edit.",
        "// Geodata: Bundesamt für Statistik (BFS), GEOSTAT, generalised administrative boundaries (base: swisstopo).",
        "// Pre-projected (equirectangular, cos 46.8°) and simplified; canton borders are shared arcs.",
        "",
        f"export const SWISS_VIEWBOX = \"0 0 {a.width:.0f} {height}\";",
        "export const SWISS_MAP_CREDIT = \"Map: BFS GEOSTAT / swisstopo (via swiss-maps)\";",
        "",
        "export const CANTON_PATHS: Record<string, string> = {",
        *[f"  {c}: \"{cantons[c]}\"," for c in sorted(cantons)],
        "};",
        "",
        "export const LAKE_PATHS: string[] = [",
        *[f"  \"{d}\"," for d in lakes],
        "];",
        "",
    ]
    OUT.write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: 26 cantons, {len(lakes)} lakes, viewBox 0 0 {a.width:.0f} {height}, "
          f"{OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
