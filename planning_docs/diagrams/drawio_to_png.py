"""Render a draw.io file written by the generators in this folder to a PNG, without the draw.io application.

The generators use plain rectangles, containers, text cells and orthogonal edges, so this renderer covers only
those. Run:  python planning_docs/diagrams/drawio_to_png.py <file.drawio> <out.png> [scale]
It writes an HTML page with an SVG copy of the diagram into the scratch folder and screenshots it with Playwright
from the agentregistry UI's node_modules (the only install on this machine).
"""
from __future__ import annotations

import html
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PLAYWRIGHT = "/Users/rajaraman.m/Projects/agentregistry/ui/node_modules/playwright/index.mjs"


def _style(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
        elif part:
            out[part] = "1"
    return out


def _wrap(text: str, width: float, size: float) -> list[str]:
    per_line = max(4, int(width / (size * 0.55)))
    lines: list[str] = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > per_line:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
    return lines


def to_svg(path: Path) -> tuple[str, int, int]:
    root = ET.parse(path).getroot()
    model = root.find(".//mxGraphModel")
    width, height = int(model.get("pageWidth", 1700)), int(model.get("pageHeight", 1200))
    cells = {c.get("id"): c for c in root.findall(".//mxCell")}

    def absolute(cid: str) -> tuple[float, float, float, float]:
        c = cells[cid]
        g = c.find("mxGeometry")
        x, y, w, h = (float(g.get(k, 0)) for k in ("x", "y", "width", "height"))
        p = c.get("parent")
        if p and p in cells and p not in ("0", "1"):
            px, py, _, _ = absolute(p)
            x, y = x + px, y + py
        return x, y, w, h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">',
           '<defs><marker id="ah" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="#333333"/></marker></defs>',
           f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>']
    # vertices in document order, so containers (written first) sit under their children
    for cid, c in cells.items():
        if c.get("vertex") != "1":
            continue
        st = _style(c.get("style"))
        x, y, w, h = absolute(cid)
        text = html.unescape(c.get("value") or "")
        size = float(st.get("fontSize", 10))
        weight = "bold" if int(st.get("fontStyle", "0")) & 1 else "normal"
        italic = "italic" if int(st.get("fontStyle", "0")) & 2 else "normal"
        if st.get("text") == "1":
            lines = _wrap(text, w, size)
            for i, line in enumerate(lines):
                out.append(f'<text x="{x}" y="{y + h / 2 + (i - (len(lines) - 1) / 2) * size * 1.25 + size * 0.35}" font-size="{size}" '
                           f'font-weight="{weight}" font-style="{italic}" fill="#111111">{html.escape(line)}</text>')
            continue
        fill, stroke, sw = st.get("fillColor", "#ffffff"), st.get("strokeColor", "#666666"), st.get("strokeWidth", "1")
        if st.get("shape") == "cylinder3":
            out.append(f'<rect x="{x}" y="{y + 6}" width="{w}" height="{h - 12}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
                       f'<ellipse cx="{x + w / 2}" cy="{y + 6}" rx="{w / 2}" ry="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
                       f'<path d="M{x},{y + h - 6} a{w / 2},6 0 0 0 {w},0" fill="none" stroke="{stroke}" stroke-width="{sw}"/>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{8 if st.get("rounded") == "1" else 0}" '
                       f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        lines = _wrap(text, w - 10, size)
        top = st.get("verticalAlign") == "top"
        for i, line in enumerate(lines):
            cy = (y + 6 + size + i * size * 1.25) if top else (y + h / 2 + (i - (len(lines) - 1) / 2) * size * 1.25 + size * 0.35)
            out.append(f'<text x="{x + w / 2}" y="{cy}" text-anchor="middle" font-size="{size}" font-weight="{weight}" '
                       f'font-style="{italic}" fill="#111111">{html.escape(line)}</text>')
    # edges
    for cid, c in cells.items():
        if c.get("edge") != "1":
            continue
        st = _style(c.get("style"))
        sx, sy, sw_, sh = absolute(c.get("source"))
        tx, ty, tw, th = absolute(c.get("target"))
        ex, ey = sx + sw_ * float(st.get("exitX", 0.5)), sy + sh * float(st.get("exitY", 1))
        nx, ny = tx + tw * float(st.get("entryX", 0.5)), ty + th * float(st.get("entryY", 0))
        horizontal = float(st.get("exitY", 1)) in (0.5,) or float(st.get("entryY", 0)) in (0.5,)
        if horizontal:
            mx = (ex + nx) / 2
            pts = [(ex, ey), (mx, ey), (mx, ny), (nx, ny)]
        else:
            my = (ey + ny) / 2
            pts = [(ex, ey), (ex, my), (nx, my), (nx, ny)]
        d = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py) in enumerate(pts))
        dash = ' stroke-dasharray="7 5"' if st.get("dashed") == "1" else ""
        out.append(f'<path d="{d}" fill="none" stroke="#333333" stroke-width="1.6" marker-end="url(#ah)"{dash}/>')
        label = html.unescape(c.get("value") or "")
        if label:
            lx, ly = pts[1][0] if horizontal else (pts[1][0] + pts[2][0]) / 2, pts[1][1] if not horizontal else (pts[1][1] + pts[2][1]) / 2
            size = float(st.get("fontSize", 9))
            tw_ = len(label) * size * 0.55 + 10
            out.append(f'<rect x="{lx - tw_ / 2}" y="{ly - size * 0.8}" width="{tw_}" height="{size * 1.6}" fill="#ffffff" opacity="0.95"/>'
                       f'<text x="{lx}" y="{ly + size * 0.35}" text-anchor="middle" font-size="{size}" fill="#111111">{html.escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out), width, height


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    svg, width, height = to_svg(src)
    work = Path(tempfile.mkdtemp(prefix="drawio-png-"))
    page = work / "page.html"
    page.write_text(f"<!doctype html><html><body style='margin:0'>{svg}</body></html>", encoding="utf-8")
    script = work / "shot.mjs"
    script.write_text(f"""import {{ chromium }} from '{PLAYWRIGHT}';
const b = await chromium.launch();
const p = await b.newPage({{ viewport: {{ width: {width}, height: {height} }}, deviceScaleFactor: {scale} }});
await p.goto('file://{page}');
await p.locator('svg').screenshot({{ path: '{dst}' }});
await b.close();
""", encoding="utf-8")
    subprocess.run(["node", str(script)], check=True, env={**os.environ})
    print(f"wrote {dst} ({width}x{height} at {scale}x)")


if __name__ == "__main__":
    main()
