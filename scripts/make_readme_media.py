"""Animated, theme-aware SVGs for the README -> docs/assets/readme/*.svg (generated, committed).

    python scripts/make_readme_media.py --run ~/Developer/sentinel-runs/mc_0656_final

  how-it-works.svg  listen -> six AI checks -> decide -> prove, with a pulse running through (illustrative quote taken
                    from the fictional case call call_041)
  threshold.svg     the 62 case calls at their real judge risk (run's judge/*.json) coloured by their real decision
                    (results/*.json); the review line sweeps 0.20 -> 0.68 and back, and each call turns grey while the
                    line is above its risk: what the threshold slider does, from the shipped run, no labels used
  deployment.svg    what runs where: GPU server (Whisper + Apertus via vLLM) and workstation inside one boundary,
                    joined by an SSH tunnel; no cloud AI API

Every SVG carries its own light and dark palette (prefers-color-scheme) and stops all motion under
prefers-reduced-motion, showing the final state. Plain SVG + CSS: renders in GitHub's <img>, no script, no fonts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "assets" / "readme"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

PALETTE = """
  :root { --bg:#ffffff; --ink:#1f2328; --muted:#59636e; --line:#d1d9e0; --card:#f6f8fa;
          --alarm:#cf222e; --review:#9a6700; --ok:#8c959f; --accent:#0969da; --good:#1a7f37; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0d1117; --ink:#e6edf3; --muted:#9198a1; --line:#3d444d; --card:#151b23;
            --alarm:#ff7b72; --review:#d29922; --ok:#656c76; --accent:#4493f8; --good:#3fb950; } }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
  text { font-family: %s; fill: var(--ink); }
  .muted { fill: var(--muted); } .card { fill: var(--card); stroke: var(--line); }
""" % FONT


def svg(w: int, h: int, title: str, style: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{title}"><title>{title}</title><style>{PALETTE}{style}</style>'
            f'<rect width="{w}" height="{h}" rx="12" fill="var(--bg)"/>{body}</svg>\n')


def how_it_works() -> str:
    W, H = 960, 330
    cols = [(20, "1", "Listen", "Swiss German speech to text", "Whisper large-v3-turbo · 5.5 s per call"),
            (260, "2", "Check", "one AI check per kind of fraud", "Apertus 8B · must quote the words"),
            (500, "3", "Decide", "alarm · review · no alert", "risk = max over the checks"),
            (740, "4", "Prove", "quote, time, playable clip", "every citation checked word for word")]
    b = []
    for x, n, head, sub, foot in cols:
        b.append(f'<rect class="card" x="{x}" y="20" width="200" height="290" rx="10"/>'
                 f'<circle cx="{x + 24}" cy="46" r="12" fill="var(--accent)"/>'
                 f'<text x="{x + 24}" y="51" font-size="13" font-weight="700" text-anchor="middle" style="fill:var(--bg)">{n}</text>'
                 f'<text x="{x + 44}" y="52" font-size="17" font-weight="700">{head}</text>'
                 f'<text class="muted" x="{x + 16}" y="80" font-size="12">{sub}</text>'
                 f'<text class="muted" x="{x + 16}" y="296" font-size="11">{foot}</text>')
    # 1 listen: waveform bars, animated
    for i in range(22):
        hgt = 10 + (i * 37 % 46)
        b.append(f'<rect class="wave" x="{36 + i * 7}" y="{170 - hgt / 2}" width="4" height="{hgt}" rx="2" '
                 f'fill="var(--accent)" style="animation-delay:{(i % 7) * 0.12:.2f}s"/>')
    b.append('<text x="36" y="232" font-size="12" font-family="ui-monospace,Menlo,monospace">00:44 Kunde:</text>'
             '<text x="36" y="250" font-size="12" font-family="ui-monospace,Menlo,monospace">«Quartalszahlen sind</text>'
             '<text x="36" y="268" font-size="12" font-family="ui-monospace,Menlo,monospace"> viel besser …»</text>')
    # 2 check: six criteria light up one after the other; insider trading stays lit
    crit = ["Insider trading", "Credential sharing", "Third-party disclosure", "Documentation concealment",
            "Control evasion", "Payment card data"]
    for i, c in enumerate(crit):
        y = 100 + i * 30
        hit = " hit" if i == 0 else ""
        b.append(f'<g class="chip{hit}" style="animation-delay:{0.4 + i * 0.35:.2f}s">'
                 f'<rect x="272" y="{y}" width="176" height="22" rx="11" fill="none" stroke="var(--line)"/>'
                 f'<text x="284" y="{y + 15}" font-size="11.5">{c}</text></g>')
    # 3 decide: risk bar fills past the alarm line, badge pulses
    b.append('<text class="muted" x="516" y="116" font-size="12">call risk</text>'
             '<rect x="516" y="126" width="168" height="14" rx="7" fill="var(--line)"/>'
             '<rect class="risk" x="516" y="126" width="168" height="14" rx="7" fill="var(--alarm)"/>'
             '<line x1="634" y1="118" x2="634" y2="148" stroke="var(--ink)" stroke-width="2"/>'
             '<text class="muted" x="634" y="164" font-size="11" text-anchor="middle">alarm 0.70</text>'
             '<line x1="550" y1="118" x2="550" y2="148" stroke="var(--muted)" stroke-dasharray="3 3"/>'
             '<text class="muted" x="550" y="164" font-size="11" text-anchor="middle">review 0.20</text>'
             '<g class="badge"><rect x="540" y="196" width="120" height="40" rx="20" fill="var(--alarm)"/>'
             '<text x="600" y="221" font-size="15" font-weight="700" text-anchor="middle" style="fill:var(--bg)">ALARM</text></g>'
             '<text class="muted" x="516" y="262" font-size="11">not sure → review, never a</text>'
             '<text class="muted" x="516" y="276" font-size="11">confident alarm</text>')
    # 4 prove: evidence card with clip progress
    b.append('<rect x="756" y="100" width="168" height="150" rx="8" fill="var(--bg)" stroke="var(--line)"/>'
             '<text x="768" y="122" font-size="12" font-weight="700" style="fill:var(--alarm)">Insider trading</text>'
             '<text x="768" y="142" font-size="11" class="muted">00:44–00:49 · customer</text>'
             '<text x="768" y="164" font-size="11">«Diese sind wohl</text>'
             '<text x="768" y="180" font-size="11">nicht publiziert.»</text>'
             '<rect x="768" y="200" width="144" height="6" rx="3" fill="var(--line)"/>'
             '<rect class="clip" x="768" y="200" width="144" height="6" rx="3" fill="var(--accent)"/>'
             '<text x="768" y="230" font-size="11" class="muted">▶ clip ±10 s · citation ✓</text>')
    # the pulse running through
    for x in (220, 460, 700):
        b.append(f'<path d="M{x + 2} 165 h36" stroke="var(--line)" stroke-width="2"/>'
                 f'<circle class="pulse" cx="{x + 4}" cy="165" r="4" fill="var(--accent)"/>')
    style = """
  .wave { transform-box: fill-box; transform-origin: center; animation: wave 1.1s ease-in-out infinite alternate; }
  @keyframes wave { from { transform: scaleY(.35); } to { transform: scaleY(1); } }
  .chip rect { transition: none; } .chip { animation: chip 6s infinite; }
  @keyframes chip { 0%, 4% { opacity: .35; } 8%, 100% { opacity: 1; } }
  .chip.hit rect { stroke: var(--alarm); stroke-width: 2; } .chip.hit text { fill: var(--alarm); font-weight: 700; }
  .risk { transform-box: fill-box; transform-origin: left; animation: risk 6s ease-out infinite; }
  @keyframes risk { 0%, 35% { transform: scaleX(.02); } 60%, 100% { transform: scaleX(.94); } }
  .badge { transform-box: fill-box; transform-origin: center; animation: badge 6s infinite; }
  @keyframes badge { 0%, 58% { opacity: 0; transform: scale(.8); } 64% { opacity: 1; transform: scale(1.08); }
                     70%, 100% { opacity: 1; transform: scale(1); } }
  .clip { transform-box: fill-box; transform-origin: left; animation: clip 6s linear infinite; }
  @keyframes clip { 0%, 70% { transform: scaleX(0); } 100% { transform: scaleX(1); } }
  .pulse { animation: pulse 2s linear infinite; }
  @keyframes pulse { from { transform: translateX(0); opacity: 1; } to { transform: translateX(32px); opacity: .2; } }
"""
    return svg(W, H, "How SENTINEL handles one call: listen, check, decide, prove", style, "".join(b))


def threshold(run: Path) -> str:
    judge = {p.stem: json.loads(p.read_text(encoding="utf-8"))["risk"] for p in sorted((run / "judge").glob("call_0*.json"))}
    dec = {p.stem: json.loads(p.read_text(encoding="utf-8"))["decision"] for p in sorted((run / "results").glob("call_0*.json"))}
    W, H, X0, X1, BASE = 960, 300, 200, 920, 200
    x = lambda r: X0 + r * (X1 - X0)                                          # noqa: E731
    stacks: dict[int, int] = {}
    b, style = [], []
    lo, hi, period = 0.20, 0.68, 9.0
    counts = {k: sum(v == k for v in dec.values()) for k in ("alarm", "review", "no_alert")}
    zeros = sorted(c for c in judge if judge[c] == 0)
    for i, cid in enumerate(zeros):          # risk 0: a block, not a 49-dot tower
        cx, cy = 34 + (i % 12) * 11, BASE - 8 - (i // 12) * 11
        fill = {"alarm": "var(--alarm)", "review": "var(--review)"}.get(dec[cid], "var(--ok)")
        b.append(f'<circle cx="{cx}" cy="{cy}" r="4.6" fill="{fill}"><title>{cid}: risk 0.00, {dec[cid]}</title></circle>')
    b.append(f'<text class="muted" x="34" y="{BASE - 8 - ((len(zeros) - 1) // 12 + 1) * 11 - 4}" font-size="11">'
             f'risk 0: {len(zeros)} calls</text>')
    for i, cid in enumerate(sorted((c for c in judge if judge[c] > 0), key=lambda c: (judge[c], c))):
        r, d = judge[cid], dec[cid]
        col = round(x(r) / 11)
        k = stacks.get(col, 0)
        stacks[col] = k + 1
        cx, cy = col * 11, BASE - 8 - k * 11
        fill = {"alarm": "var(--alarm)", "review": "var(--review)"}.get(d, "var(--ok)")
        cls = ""
        if d == "review" and r < hi:            # the moving review line passes it: grey while the line is above r
            t1 = (r - lo) / (hi - lo) * 50 if r > lo else 0.0
            cls = f' class="d{i}"'
            style.append(f".d{i} {{ animation: d{i} {period}s linear infinite; }} "
                         f"@keyframes d{i} {{ 0%, {max(t1 - .01, 0):.2f}% {{ fill: var(--review); }} "
                         f"{t1:.2f}%, {100 - t1:.2f}% {{ fill: var(--ok); }} {min(100 - t1 + .01, 100):.2f}%, 100% {{ fill: var(--review); }} }}")
        b.append(f'<circle{cls} cx="{cx}" cy="{cy}" r="4.6" fill="{fill}"><title>{cid}: risk {r:.2f}, {d}</title></circle>')
    axis = "".join(f'<line x1="{x(t)}" y1="{BASE}" x2="{x(t)}" y2="{BASE + 5}" stroke="var(--muted)"/>'
                   f'<text class="muted" x="{x(t)}" y="{BASE + 20}" font-size="11" text-anchor="middle">{t:.1f}</text>'
                   for t in (0, .2, .4, .6, .8, 1.0))
    body = (f'<text x="24" y="34" font-size="16" font-weight="700">The threshold, on the 62 case calls</text>'
            f'<text class="muted" x="24" y="54" font-size="12">each dot is one call at its AI-judge risk · shipped thresholds: '
            f'{counts["alarm"]} alarm · {counts["review"]} review · {counts["no_alert"]} no alert · the review line sweeps 0.20 → 0.68 and back</text>'
            + "".join(b)
            + f'<line x1="{X0}" y1="{BASE}" x2="{X1}" y2="{BASE}" stroke="var(--line)"/>' + axis
            + f'<text class="muted" x="{(X0 + X1) / 2}" y="{BASE + 38}" font-size="11" text-anchor="middle">call risk (max over the six checks)</text>'
            f'<line x1="{x(.7)}" y1="70" x2="{x(.7)}" y2="{BASE}" stroke="var(--alarm)" stroke-width="2"/>'
            f'<text x="{x(.7) + 6}" y="82" font-size="12" style="fill:var(--alarm)">alarm 0.70</text>'
            f'<g class="rev"><line x1="{x(lo)}" y1="70" x2="{x(lo)}" y2="{BASE}" stroke="var(--review)" stroke-width="2" stroke-dasharray="5 4"/>'
            f'<text x="{x(lo) + 6}" y="82" font-size="12" style="fill:var(--review)">review</text></g>'
            f'<circle cx="40" cy="{H - 26}" r="5" fill="var(--alarm)"/><text x="50" y="{H - 22}" font-size="12">alarm</text>'
            f'<circle cx="110" cy="{H - 26}" r="5" fill="var(--review)"/><text x="120" y="{H - 22}" font-size="12">review (a person looks)</text>'
            f'<circle cx="290" cy="{H - 26}" r="5" fill="var(--ok)"/><text x="300" y="{H - 22}" font-size="12">no alert</text>'
            f'<text class="muted" x="{W - 24}" y="{H - 22}" font-size="11" text-anchor="end">run mc_0656_final · Settings → Threshold re-decides from cache in milliseconds</text>')
    dx = x(hi) - x(lo)
    css = (f".rev {{ animation: rev {period}s linear infinite; }} "
           f"@keyframes rev {{ 0% {{ transform: translateX(0); }} 50% {{ transform: translateX({dx:.1f}px); }} 100% {{ transform: translateX(0); }} }}\n"
           + "\n".join(style))
    return svg(W, H, "The 62 case calls by AI-judge risk; moving the review threshold changes which calls a person sees", css, body)


def deployment() -> str:
    W, H = 960, 300
    body = ('<rect x="16" y="16" width="928" height="268" rx="14" fill="none" stroke="var(--good)" stroke-width="2" stroke-dasharray="8 6"/>'
            '<text x="36" y="44" font-size="13" font-weight="700" style="fill:var(--good)">YOUR ENVIRONMENT · nothing leaves · services bind to 127.0.0.1</text>'
            '<rect class="card" x="40" y="70" width="330" height="190" rx="10"/>'
            '<text x="60" y="98" font-size="16" font-weight="700">GPU server</text>'
            '<text class="muted" x="60" y="118" font-size="12">hackathon: rented A40 · target: on-prem or Swiss region</text>'
            '<rect x="60" y="136" width="290" height="44" rx="8" fill="var(--bg)" stroke="var(--line)"/>'
            '<text x="74" y="156" font-size="13" font-weight="700">faster-whisper large-v3-turbo</text>'
            '<text class="muted" x="74" y="172" font-size="11">Swiss German ASR · 5.5 s per call</text>'
            '<rect x="60" y="192" width="290" height="44" rx="8" fill="var(--bg)" stroke="var(--line)"/>'
            '<text x="74" y="212" font-size="13" font-weight="700">Apertus v1.5 8B via vLLM</text>'
            '<text class="muted" x="74" y="228" font-size="11">open weights · six checks · :8000</text>'
            '<rect class="card" x="590" y="70" width="330" height="190" rx="10"/>'
            '<text x="610" y="98" font-size="16" font-weight="700">Workstation</text>'
            '<text class="muted" x="610" y="118" font-size="12">./run.sh · scripts/run_test_set.sh · web app</text>'
            '<rect x="610" y="136" width="290" height="44" rx="8" fill="var(--bg)" stroke="var(--line)"/>'
            '<text x="624" y="156" font-size="13" font-weight="700">pipeline · decision · evidence check</text>'
            '<text class="muted" x="624" y="172" font-size="11">decisions, snippets, audit record</text>'
            '<rect x="610" y="192" width="290" height="44" rx="8" fill="var(--bg)" stroke="var(--line)"/>'
            '<text x="624" y="212" font-size="13" font-weight="700">compliance officer UI</text>'
            '<text class="muted" x="624" y="228" font-size="11">alerts · threshold · quality · audit</text>'
            '<path d="M372 165 H588" stroke="var(--line)" stroke-width="10" stroke-linecap="round"/>'
            '<text x="480" y="150" font-size="12" text-anchor="middle" font-weight="700">SSH tunnel</text>'
            '<text class="muted" x="480" y="196" font-size="11" text-anchor="middle">audio → GPU · text ← back</text>'
            '<circle class="pk a" cx="380" cy="165" r="4" fill="var(--accent)"/>'
            '<circle class="pk b" cx="380" cy="165" r="4" fill="var(--accent)"/>'
            '<circle class="pk c" cx="580" cy="165" r="4" fill="var(--good)"/>'
            '<g transform="translate(390 262)"><rect x="0" y="-16" width="180" height="26" rx="13" fill="var(--bg)" stroke="var(--alarm)"/>'
            '<text x="90" y="2" font-size="12" text-anchor="middle" style="fill:var(--alarm)">✕ no cloud AI API called</text></g>')
    css = """
  .pk.a { animation: right 2.4s linear infinite; } .pk.b { animation: right 2.4s linear infinite 1.2s; }
  .pk.c { animation: left 2.4s linear infinite .6s; }
  @keyframes right { from { transform: translateX(0); opacity: 1; } to { transform: translateX(200px); opacity: .3; } }
  @keyframes left { from { transform: translateX(0); opacity: 1; } to { transform: translateX(-200px); opacity: .3; } }
"""
    return svg(W, H, "Deployment: GPU server and workstation inside one environment, joined by an SSH tunnel; no cloud AI API", css, body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="pipeline run folder with judge/ and results/")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in (("how-it-works.svg", how_it_works()), ("threshold.svg", threshold(a.run.expanduser())),
                       ("deployment.svg", deployment())):
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"wrote docs/assets/readme/{name} ({len(text) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
