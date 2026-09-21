"""Lecture directe d'un titre sur Spotify (« mets Life de Damso sur Spotify »).

Comment ça marche (API Web officielle de Spotify, gratuite, sans clé secrète) :
  1. tu crées une petite « application » sur https://developer.spotify.com/dashboard et tu colles son
     Client ID dans l'onglet Musique ;
  2. tu cliques sur « Connecter » : le navigateur s'ouvre, tu autorises Sentinel (connexion PKCE, aucun
     mot de passe ni secret n'est stocké, seulement un jeton renouvelable dans %APPDATA%\\Sentinel) ;
  3. ensuite Sentinel cherche le titre, lance l'application Spotify si besoin et le joue.

Règle imposée par Spotify (2026) : commander la lecture par l'API demande un compte PREMIUM. Sans Premium
(ou sans connexion), Sentinel retombe automatiquement sur YouTube pour que la musique se lance quand même.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..config import data_dir
from ..nlu import normalize
from ..replies import R

log = logging.getLogger("sentinel.spotify")

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
REDIRECT_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"


class SpotifyError(Exception):
    """kind : not_connected | no_premium | no_device | not_found | network"""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind)
        self.kind, self.detail = kind, detail


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:100]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def uri_from_url(url: str) -> str | None:
    """https://open.spotify.com/playlist/ID?si=… ou spotify:playlist:ID -> spotify:playlist:ID"""
    m = re.search(r"spotify[:/](track|album|playlist|artist)[:/]([A-Za-z0-9]+)", url)
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else None


class Spotify:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._file = data_dir() / "spotify_token.json"
        self._tok: dict = {}
        self._lock = threading.Lock()
        try:
            self._tok = json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:
            self._tok = {}

    # ------------------------------------------------------------------ état
    def connected(self) -> bool:
        return bool(self.cfg["spotify_client_id"].strip() and self._tok.get("refresh_token"))

    def disconnect(self) -> None:
        self._tok = {}
        try:
            self._file.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ HTTP
    @staticmethod
    def _http(req: urllib.request.Request, timeout: float = 10) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else {})
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise SpotifyError("network", str(exc)) from exc

    def _token_request(self, form: dict) -> dict:
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        status, body = self._http(req)
        if status != 200 or "access_token" not in body:
            raise SpotifyError("not_connected", str(body))
        body["expires_at"] = time.time() + int(body.get("expires_in", 3600)) - 60
        return body

    def _save(self, body: dict) -> None:
        keep_refresh = body.get("refresh_token") or self._tok.get("refresh_token")
        self._tok = {"access_token": body["access_token"], "refresh_token": keep_refresh, "expires_at": body["expires_at"]}
        try:
            self._file.write_text(json.dumps(self._tok), encoding="utf-8")
        except OSError:
            log.warning("jeton Spotify non enregistré")

    def _access_token(self) -> str:
        with self._lock:
            if not self.connected():
                raise SpotifyError("not_connected")
            if time.time() >= self._tok.get("expires_at", 0):
                body = self._token_request({"grant_type": "refresh_token", "refresh_token": self._tok["refresh_token"],
                                            "client_id": self.cfg["spotify_client_id"].strip()})
                self._save(body)
            return self._tok["access_token"]

    def _api(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> tuple[int, dict]:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}
            data = json.dumps(body).encode("utf-8") if body is not None else None
            status, out = self._http(urllib.request.Request(url, data=data, headers=headers, method=method))
            if status == 401 and attempt == 1:
                self._tok["expires_at"] = 0                      # jeton refusé : on force le renouvellement
                continue
            return status, out
        return 401, {}

    # ------------------------------------------------------------------ connexion (une seule fois)
    def connect_blocking(self, timeout: float = 180.0) -> str:
        """Ouvre le navigateur, attend l'autorisation, enregistre le jeton. Retourne un message pour l'utilisateur."""
        client_id = self.cfg["spotify_client_id"].strip()
        if not client_id:
            return "Colle d'abord ton Client ID Spotify."
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(12)
        result: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:                            # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                result["code"] = (q.get("code") or [None])[0]
                result["error"] = (q.get("error") or [None])[0]
                result["state"] = (q.get("state") or [None])[0]
                page = ("<html><meta charset='utf-8'><body style='font-family:Segoe UI;background:#050B14;color:#D6F3FF;"
                        "text-align:center;padding-top:80px'><h2>Sentinel est connecté à Spotify ✔</h2>"
                        "<p>Tu peux fermer cet onglet.</p></body></html>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, *a) -> None:
                pass

        try:
            server = HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
        except OSError as exc:
            return f"Impossible d'ouvrir le port {REDIRECT_PORT} pour la connexion ({exc})."
        server.timeout = 2
        params = {"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI, "scope": SCOPES,
                  "code_challenge_method": "S256", "code_challenge": challenge, "state": state}
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode(params))
        deadline = time.time() + timeout
        try:
            while time.time() < deadline and not result:
                server.handle_request()
        finally:
            server.server_close()
        if not result or result.get("error") or not result.get("code"):
            return "Connexion Spotify annulée ou expirée."
        if result.get("state") != state:
            return "Connexion Spotify refusée (état invalide)."
        try:
            body = self._token_request({"grant_type": "authorization_code", "code": result["code"],
                                        "redirect_uri": REDIRECT_URI, "client_id": client_id, "code_verifier": verifier})
        except SpotifyError as exc:
            return f"Spotify a refusé la connexion : {exc.detail[:120]}"
        self._save(body)
        return "Spotify connecté ✔"

    # ------------------------------------------------------------------ recherche
    @staticmethod
    def _clean_query(q: str) -> str:
        q = re.sub(r"\b(?:sur|avec|dans|via)\s+spotify\b", " ", q, flags=re.I)
        q = re.sub(r"\s+\b(?:de|par)\b\s+", " ", " " + q + " ")             # « Life de Damso » -> « Life Damso »
        return re.sub(r"\s+", " ", q).strip()

    def search(self, query: str, kind: str = "track") -> dict | None:
        q = self._clean_query(query)
        if not q:
            return None
        status, body = self._api("GET", "/search", {"q": q, "type": kind, "limit": 10})
        if status == 403:
            raise SpotifyError("no_premium", str(body))
        if status != 200:
            raise SpotifyError("network", f"HTTP {status}")
        items = (body.get(kind + "s") or {}).get("items") or []
        items = [i for i in items if i]
        if not items:
            return None
        if kind != "track":
            return items[0]
        wanted = normalize(q)

        def score(idx_item: tuple[int, dict]) -> float:
            idx, it = idx_item
            label = normalize(f"{it.get('name', '')} {' '.join(a.get('name', '') for a in it.get('artists', []))}")
            return SequenceMatcher(None, wanted, label).ratio() + (0.08 if idx == 0 else 0.0)

        return max(enumerate(items), key=score)[1]

    # ------------------------------------------------------------------ lecture
    def _device(self) -> str | None:
        status, body = self._api("GET", "/me/player/devices")
        devices = [d for d in (body.get("devices") or []) if not d.get("is_restricted")]
        if not devices:
            return None
        for d in devices:
            if d.get("is_active"):
                return d["id"]
        computers = [d for d in devices if str(d.get("type", "")).lower() == "computer"]
        return (computers or devices)[0]["id"]

    def _ensure_device(self, wait: float = 15.0) -> str:
        device = self._device()
        if device:
            return device
        try:
            os.startfile("spotify:")                                # lance l'application Spotify
        except Exception:
            log.debug("lancement de Spotify impossible", exc_info=True)
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(1.2)
            device = self._device()
            if device:
                return device
        raise SpotifyError("no_device")

    def _play(self, body: dict) -> None:
        device = self._ensure_device()
        status, out = self._api("PUT", "/me/player/play", {"device_id": device}, body)
        if status in (200, 202, 204):
            return
        if status == 403:
            raise SpotifyError("no_premium", str(out))
        if status == 404:
            raise SpotifyError("no_device", str(out))
        raise SpotifyError("network", f"HTTP {status}")

    def play(self, query: str, artist_only: bool = False) -> str:
        """Cherche puis joue. Lève SpotifyError si ça ne marche pas (l'appelant choisit le repli)."""
        if not self.connected():
            raise SpotifyError("not_connected")
        if artist_only:
            artist = self.search(query, "artist")
            if not artist:
                raise SpotifyError("not_found", query)
            self._play({"context_uri": artist["uri"]})
            return R(self.cfg, "music_play", title=artist.get("name", query))
        track = self.search(query, "track")
        if not track:
            raise SpotifyError("not_found", query)
        self._play({"uris": [track["uri"]]})
        artists = ", ".join(a.get("name", "") for a in track.get("artists", [])[:2]) or "Spotify"
        return R(self.cfg, "spotify_play", title=track.get("name", query), artist=artists)

    def play_context(self, url_or_uri: str) -> None:
        uri = uri_from_url(url_or_uri)
        if not uri:
            raise SpotifyError("not_found", url_or_uri)
        if not self.connected():
            raise SpotifyError("not_connected")
        self._play({"uris": [uri]} if uri.startswith("spotify:track:") else {"context_uri": uri})
