"""Render docs/diagrams/*.mmd to docs/assets/*.svg with a white canvas.

    uv run python scripts/render_diagrams.py

Mermaid emits a transparent SVG, so a diagram embedded as a ```mermaid block takes
on the reader's page colour and looks different in dark mode. Rendering ahead of
time and inserting an explicit white rect makes the README look the same for
everyone. The `.mmd` sources stay the editable, diffable form.

Rendering runs in a real browser rather than through mermaid-cli, which would pull
in puppeteer and its own Chromium just to draw four pictures. Open the URL this
script prints, wait for it to report success, then stop it with Ctrl-C.
"""

from __future__ import annotations

import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "diagrams"
OUT = ROOT / "docs" / "assets"
PORT = 8899
PADDING = 8

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>render diagrams</title></head>
<body style="background:#0d1117;color:#eee;font-family:system-ui;padding:20px">
<h1 id="v">rendering…</h1><div id="out"></div>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({ startOnLoad: false });
const diagrams = __DIAGRAMS__;
const results = [];
for (const [name, src] of Object.entries(diagrams)) {
  try {
    const { svg } = await mermaid.render('r_' + name.replace(/\\W/g, ''), src);
    const holder = document.createElement('div');
    holder.innerHTML = svg;
    document.getElementById('out').appendChild(holder);
    const el = holder.querySelector('svg');
    const vb = (el.getAttribute('viewBox') || '').split(/[\\s,]+/).map(Number);
    const pad = __PADDING__;
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    const box = vb.length === 4;
    rect.setAttribute('x', box ? vb[0] - pad : 0);
    rect.setAttribute('y', box ? vb[1] - pad : 0);
    rect.setAttribute('width', box ? vb[2] + pad * 2 : '100%');
    rect.setAttribute('height', box ? vb[3] + pad * 2 : '100%');
    rect.setAttribute('fill', '#ffffff');
    el.insertBefore(rect, el.firstChild);
    el.setAttribute('style', 'background-color:#ffffff');
    const out = new XMLSerializer().serializeToString(el);
    const r = await fetch('/save', { method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, svg: out }) });
    results.push(`${name}: ${r.ok ? 'saved' : 'FAILED'}`);
  } catch (e) { results.push(`${name}: ERROR ${e}`); }
}
document.getElementById('v').textContent = 'DONE — ' + results.join(' | ');
</script></body></html>"""


def _diagrams() -> dict[str, str]:
    sources = {p.stem: p.read_text(encoding="utf-8") for p in sorted(SRC.glob("*.mmd"))}
    if not sources:
        raise SystemExit(f"no .mmd files in {SRC}")
    return sources


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def do_GET(self) -> None:
        body = PAGE.replace("__DIAGRAMS__", json.dumps(_diagrams())).replace(
            "__PADDING__", str(PADDING)
        )
        self._respond(200, body.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        length = int(self.headers["content-length"])
        payload = json.loads(self.rfile.read(length))
        name = re.sub(r"[^a-z0-9-]", "", payload["name"])
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.svg").write_text(payload["svg"], encoding="utf-8")
        print(f"wrote docs/assets/{name}.svg")
        self._respond(200, b"ok", "text/plain")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/"
    print(f"open {url} to render {len(_diagrams())} diagrams; Ctrl-C when done")
    webbrowser.open(url)
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("stopped")
