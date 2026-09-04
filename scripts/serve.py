#!/usr/bin/env python3
"""
serve.py — local dev server for the flashcard app.

The app is fully static: everything it needs is under public/ (the shell) and
public/data/*.json (the frozen dataset, built by scripts/build_static.py). There
is no database and no API at runtime. This server just hands out those files,
plus the local audio/ and images/ folders so you can preview media before it's
pushed to the CDN.

    python3 scripts/seed_db.py --json data/corpus_words.json --reset
    python3 scripts/build_static.py
    python3 scripts/serve.py
    open http://localhost:8000
"""

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUBLIC = os.path.join(ROOT, "public")
AUDIO_DIR = os.path.join(ROOT, "audio")
IMG_DIR = os.path.join(ROOT, "images")
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".gif": "image/gif"}
CTYPE = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript",
    ".css": "text/css", ".json": "application/json",
    ".webmanifest": "application/manifest+json", ".png": "image/png",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/octet-stream", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path, ctype, extra=None):
        if not os.path.isfile(path):
            return self._send(404, "not found", "text/plain")
        with open(path, "rb") as fh:
            return self._send(200, fh.read(), ctype, extra)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            p = "/index.html"

        # local media (deployed build serves these from the CDN instead)
        if p.startswith("/audio/"):
            fp = os.path.normpath(os.path.join(ROOT, p.lstrip("/")))
            return self._file(fp if fp.startswith(AUDIO_DIR) else "", "audio/mpeg")
        if p.startswith("/img/"):
            stem = os.path.basename(p[len("/img/"):]).lower()
            for ext in IMG_EXTS:
                fp = os.path.join(IMG_DIR, stem + ext)
                if os.path.isfile(fp):
                    return self._file(fp, IMG_MIME[ext])
            return self._send(404, "no image", "text/plain")

        # everything else: a file under public/
        ext = os.path.splitext(p)[1]
        fp = os.path.normpath(os.path.join(PUBLIC, p.lstrip("/")))
        if not fp.startswith(PUBLIC):
            return self._send(403, "nope", "text/plain")
        extra = {"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"} \
            if p == "/sw.js" else None
        return self._file(fp, CTYPE.get(ext, "application/octet-stream"), extra)

    do_HEAD = do_GET


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(PUBLIC, "data", "cards.json")):
        print("!  public/data/cards.json missing — run:  python3 scripts/build_static.py")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Dutch Flashcards:  http://localhost:%d  (Ctrl+C to stop)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
