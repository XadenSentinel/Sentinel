"""Lecture de musique SANS clé d'API ni compte développeur.

Principe : yt-dlp interroge YouTube (recherche + contenu de playlist, sans
téléchargement) pour trouver l'identifiant exact de la vidéo, puis on l'ouvre
dans le navigateur, où elle démarre automatiquement.

  « mets du Damso »                    -> vidéo + mix radio qui enchaîne les titres
  « lance Life »                       -> première vidéo trouvée
  « lance Life dans la playlist Rap FR »
        -> si « rap fr » est enregistrée dans l'onglet Musique, on retrouve
           « Life » DANS cette playlist et on la lance avec la playlist.

Spotify : sans API, une appli de bureau ne peut pas lancer un titre précis
automatiquement. Le mode « Spotify » ouvre donc la recherche / la playlist
dans l'appli ; la lecture, elle, reste un clic.
"""
from __future__ import annotations

import logging
import os
import re
import webbrowser
from difflib import SequenceMatcher
from urllib.parse import parse_qs, quote, quote_plus, urlparse

from ..nlu import normalize
from ..replies import R, join
from .spotify import Spotify, SpotifyError

log = logging.getLogger("sentinel.music")


class _NullLogger:
    def debug(self, *a): pass
    def info(self, *a): pass
    def warning(self, *a): pass
    def error(self, *a): pass


def _is_spotify(url: str) -> bool:
    return url.startswith("spotify:") or "open.spotify.com" in url


def _spotify_uri(url: str) -> str:
    if url.startswith("spotify:"):
        return url
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(\w+)/(\w+)", url)
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else url


def _short(title: str, limit: int = 70) -> str:
    return title if len(title) <= limit else title[:limit].rsplit(" ", 1)[0]


class MusicPlayer:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.spotify = Spotify(cfg)

    # ------------------------------------------------------------------ API
    def play(self, query: str = "", playlist: str | None = None, radio: bool = False,
             provider: str | None = None) -> str:
        provider = provider if provider in ("spotify", "youtube", "ytmusic") else self.cfg["music_provider"]
        query = (query or "").strip()
        if not query and not playlist:
            return R(self.cfg, "music_ask")

        prefix = ""
        if playlist:
            url = self._find_playlist(playlist)
            if url:
                return self._play_playlist(url, query, playlist)
            prefix = R(self.cfg, "music_unknown_playlist", playlist=playlist)
            query = f"{query} {playlist}".strip()
            radio = False
        return join(prefix, self._play_search(query, radio, provider))

    # ------------------------------------------------------------ recherche
    def _play_search(self, query: str, radio: bool, provider: str) -> str:
        if provider == "spotify":
            return self._play_spotify(query, radio)
        return self._play_youtube(query, radio, provider)

    def _play_spotify(self, query: str, radio: bool) -> str:
        """Lecture directe via l'API Spotify ; sinon repli sur YouTube pour que la musique parte quand même."""
        try:
            return self.spotify.play(query, artist_only=radio)
        except SpotifyError as exc:
            log.info("Spotify : %s %s", exc.kind, exc.detail[:100])
            if exc.kind == "not_found":
                return R(self.cfg, "spotify_not_found", query=query)
            key = {"not_connected": "spotify_not_connected", "no_premium": "spotify_no_premium",
                   "no_device": "spotify_no_device"}.get(exc.kind)
            return join(R(self.cfg, key) if key else "", self._play_youtube(query, radio, "youtube"))

    def _play_youtube(self, query: str, radio: bool, provider: str) -> str:
        video = self._first_video(query)
        if video is None:
            webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(query))
            return R(self.cfg, "music_fallback", query=query)

        host = "music.youtube.com" if provider == "ytmusic" else "www.youtube.com"
        url = f"https://{host}/watch?v={video['id']}"
        if radio and self.cfg["music_radio"]:
            url += f"&list=RD{video['id']}"        # mix « radio » YouTube : enchaîne les titres
        webbrowser.open(url)
        return R(self.cfg, "music_play", title=_short(video.get("title") or query))

    def _first_video(self, query: str) -> dict | None:
        try:
            info = self._extract(f"ytsearch5:{query}")
        except Exception:
            log.exception("recherche yt-dlp échouée")
            return None
        for entry in info.get("entries") or []:
            if entry and entry.get("id"):
                return entry
        return None

    # ------------------------------------------------------------ playlists
    def _find_playlist(self, name: str) -> str | None:
        wanted = normalize(name)
        best_url, best = None, 0.0
        for key, url in self.cfg["playlists"].items():
            k = normalize(key)
            score = 1.0 if k == wanted else (0.9 if wanted in k or k in wanted else SequenceMatcher(None, k, wanted).ratio())
            if score > best:
                best_url, best = url, score
        return best_url if best >= 0.6 else None

    def _play_playlist(self, url: str, query: str, name: str) -> str:
        if _is_spotify(url):
            if self.spotify.connected():
                try:
                    self.spotify.play_context(url)
                    return R(self.cfg, "music_spotify_playlist", name=name)
                except SpotifyError as exc:
                    log.info("lecture de playlist Spotify impossible (%s), ouverture simple", exc.kind)
            os.startfile(_spotify_uri(url))
            return R(self.cfg, "music_spotify_playlist", name=name)

        list_id = (parse_qs(urlparse(url).query).get("list") or [None])[0]
        if not list_id:
            webbrowser.open(url)
            return R(self.cfg, "music_playlist", name=name)

        host = "music.youtube.com" if self.cfg["music_provider"] == "ytmusic" else "www.youtube.com"
        entries: list[dict] = []
        try:
            info = self._extract(f"https://www.youtube.com/playlist?list={list_id}")
            entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
        except Exception:
            log.exception("lecture de la playlist impossible")

        if not entries:
            webbrowser.open(f"https://{host}/playlist?list={list_id}")
            return R(self.cfg, "music_playlist", name=name)

        pick, note = entries[0], ""
        if query:
            found = self._best_title(entries, query)
            if found:
                pick = found
            else:
                note = R(self.cfg, "music_track_missing", query=query)
        webbrowser.open(f"https://{host}/watch?v={pick['id']}&list={list_id}")
        return join(note, R(self.cfg, "music_playlist_track", title=_short(pick.get("title") or name), name=name))

    @staticmethod
    def _best_title(entries: list[dict], query: str) -> dict | None:
        q = normalize(query)
        best, best_score = None, 0.0
        for e in entries:
            t = normalize(e.get("title") or "")
            if re.search(rf"\b{re.escape(q)}\b", t):
                score = 0.9 + 0.1 * len(q) / max(len(t), 1)     # titre le plus court = le plus précis
            else:
                score = SequenceMatcher(None, q, t).ratio()
            if score > best_score:
                best, best_score = e, score
        return best if best_score >= 0.5 else None

    # -------------------------------------------------------------- yt-dlp
    @staticmethod
    def _extract(target: str) -> dict:
        from yt_dlp import YoutubeDL

        opts = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "logger": _NullLogger(), "socket_timeout": 10,
        }
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(target, download=False) or {}
