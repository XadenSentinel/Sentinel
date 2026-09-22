"""Petit serveur HTTP local pour l'interface web.

Sécurité (l'interface peut piloter ton PC, donc on ferme toutes les portes) :
  - écoute UNIQUEMENT sur 127.0.0.1 (jamais sur le réseau) ;
  - chaque session a un jeton secret aléatoire, exigé pour toute requête d'API ; il est passé à la page dans
    la partie « # » de l'adresse, qui n'est jamais envoyée au serveur ni aux autres sites ;
  - l'en-tête Host doit être exactement 127.0.0.1:port (contre le « DNS rebinding ») ;
  - les requêtes POST refusent toute origine étrangère (contre les autres sites ouverts dans ton navigateur) ;
  - les fichiers servis sont limités au dossier « static » ; la page ne peut charger aucune ressource externe (CSP).
"""
from __future__ import annotations

import hmac
import json
import logging
import queue
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("sentinel.web")

MAX_BODY = 64 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml", ".json": "application/json"}
SAFE_PATH = re.compile(r"^[A-Za-z0-9_\-./]+$")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class WebServer:
    def __init__(self, ctx, static_dir: Path) -> None:
        self.ctx = ctx
        self.static = Path(static_dir).resolve()
        self.token = secrets.token_urlsafe(24)
        self.closing = threading.Event()
        self.httpd = _Server(("127.0.0.1", 0), self._handler())
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#t={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="sentinel-web")
        self._thread.start()
        log.info("interface web sur le port %d", self.port)

    def stop(self) -> None:
        self.closing.set()
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            log.debug("arrêt du serveur web", exc_info=True)

    def _handler(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "Sentinel"

            def log_message(self, *args) -> None:
                pass

            # ---------------------------------------------------------------- utilitaires
            def _headers(self, code: int, ctype: str, length: int | None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", CSP)

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self._headers(code, ctype, len(body))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, obj) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

            def _host_ok(self) -> bool:
                return (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{srv.port}", f"localhost:{srv.port}")

            def _authed(self, query: dict) -> bool:
                return hmac.compare_digest((query.get("t") or [""])[0], srv.token)

            # ---------------------------------------------------------------- GET
            def do_GET(self) -> None:                    # noqa: N802
                if not self._host_ok():
                    return self._json(403, {"error": "hôte refusé"})
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.startswith("/api/"):
                    if not self._authed(query):
                        return self._json(403, {"error": "jeton invalide"})
                    if url.path == "/api/state":
                        return self._json(200, srv.ctx.snapshot())
                    if url.path == "/api/events":
                        return self._sse()
                    if url.path == "/api/schema":
                        return self._json(200, srv.ctx.schema_for((query.get("page") or [""])[0]))
                    if url.path == "/api/data":
                        return self._json(200, srv.ctx.data((query.get("name") or [""])[0]))
                    return self._json(404, {"error": "inconnu"})
                self._static(url.path)

            def _static(self, path: str) -> None:
                rel = "index.html" if path in ("", "/") else path.lstrip("/")
                if not SAFE_PATH.match(rel) or ".." in rel:
                    return self._json(404, {"error": "introuvable"})
                target = (srv.static / rel).resolve()
                if srv.static not in target.parents or not target.is_file():
                    return self._json(404, {"error": "introuvable"})
                self._send(200, target.read_bytes(), MIME.get(target.suffix.lower(), "application/octet-stream"))

            def _sse(self) -> None:
                self._headers(200, "text/event-stream", None)
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = srv.ctx.bus.subscribe()
                try:
                    self.wfile.write(b"retry: 2000\n\n")
                    self.wfile.flush()
                    while not srv.closing.is_set():
                        try:
                            ev = q.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            continue
                        self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    srv.ctx.bus.unsubscribe(q)
                    self.close_connection = True

            # ---------------------------------------------------------------- POST
            def do_POST(self) -> None:                   # noqa: N802
                if not self._host_ok():
                    return self._json(403, {"error": "hôte refusé"})
                url = urlparse(self.path)
                if not self._authed(parse_qs(url.query)):
                    return self._json(403, {"error": "jeton invalide"})
                origin = self.headers.get("Origin")
                if origin and origin not in (f"http://127.0.0.1:{srv.port}", f"http://localhost:{srv.port}"):
                    return self._json(403, {"error": "origine refusée"})
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._json(415, {"error": "JSON attendu"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if not 0 <= length <= MAX_BODY:
                        return self._json(413, {"error": "trop gros"})
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError
                except (ValueError, json.JSONDecodeError):
                    return self._json(400, {"error": "JSON invalide"})
                if url.path == "/api/action":
                    return self._json(200, srv.ctx.handle_action(str(body.get("name", "")), body.get("data") or {}))
                if url.path == "/api/setting":
                    return self._json(200, srv.ctx.set_setting(str(body.get("key", "")), body.get("value")))
                self._json(404, {"error": "inconnu"})

        return Handler
