"""
Run locally:  python app.py      then open http://localhost:8000
Optional: set ANTHROPIC_API_KEY first to use Claude. Without it, the app runs in a
clearly labeled offline demo mode (rule-based, no AI).
Standard library only - nothing to install.

Hosting (e.g. Render): set HOST=0.0.0.0 and ANTHROPIC_API_KEY. The host provides PORT.
DAILY_AI_LIMIT caps Claude calls per day (default 200) so a public link can't run up the bill;
after the cap, the app falls back to offline mode and says so.
"""

import json
import os
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from explainer import MAX_CHARS, MODEL, explain

ROOT = Path(__file__).parent
SAMPLES = ROOT / "samples"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
DAILY_AI_LIMIT = int(os.environ.get("DAILY_AI_LIMIT", "200"))
MAX_BODY_BYTES = MAX_CHARS * 4 + 1024  # generous for UTF-8 + JSON wrapping


class DailyCap:
    """Counts Claude calls per calendar day (server time). Thread-safe."""

    def __init__(self, limit: int):
        self.limit, self.day, self.count = limit, date.today(), 0
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            if date.today() != self.day:
                self.day, self.count = date.today(), 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True


cap = DailyCap(DAILY_AI_LIMIT)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html")
        if self.path == "/api/samples":
            items = [{"name": p.stem, "text": p.read_text(encoding="utf-8")}
                     for p in sorted(SAMPLES.glob("*.txt"))]
            mode = "ai" if os.environ.get("ANTHROPIC_API_KEY") else "offline"
            return self._send(200, json.dumps({"samples": items, "mode": mode, "model": MODEL}))
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/explain":
            return self._send(404, json.dumps({"error": "not found"}))
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY_BYTES:
            return self._send(413, json.dumps({"error": "That letter is too long. Paste only the main pages."}))
        try:
            letter = json.loads(self.rfile.read(length) or b"{}").get("letter", "")
        except (json.JSONDecodeError, AttributeError):
            return self._send(400, json.dumps({"error": "Bad request"}))

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        notice = None
        if api_key and not cap.take():
            api_key, notice = "", ("The daily limit for AI explanations has been reached, "
                                   "so this result uses offline rules (no AI).")
        result = explain(letter, api_key=api_key or "")
        if notice and "error" not in result:
            result["notice"] = notice
        self._send(200, json.dumps(result))

    def log_message(self, fmt, *args):  # quieter console
        pass


if __name__ == "__main__":
    mode = "Claude (" + MODEL + ")" if os.environ.get("ANTHROPIC_API_KEY") else "OFFLINE DEMO MODE (no API key set)"
    print(f"Letter Explainer running on {HOST}:{PORT}  -  {mode}")
    if HOST in ("127.0.0.1", "localhost"):
        try:
            webbrowser.open(f"http://localhost:{PORT}")
        except Exception:
            pass
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
