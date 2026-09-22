"""Extrait le texte de {"actions": [...], "say": "..."} AU FUR ET À MESURE qu'il arrive en flux,
pour que Sentinel commence à parler avant que l'IA ait fini d'écrire toute sa réponse.

Principe, volontairement prudent : on ne parle en direct QUE si le champ "actions" s'est refermé
VIDE ("actions":[]) avant que "say" ne commence — autrement dit, seulement pour une discussion pure,
jamais pendant qu'une action doit encore s'exécuter (on ne veut jamais parler d'une action avant
qu'elle soit vraiment faite). Dans tous les autres cas, Sentinel attend la réponse complète comme
avant : rien ne change côté sécurité, ce module ne fait qu'accélérer le cas "il discute".
"""
from __future__ import annotations

import re

_EMPTY_ACTIONS = re.compile(r'"actions"\s*:\s*\[\s*\]')
_NONEMPTY_ACTIONS = re.compile(r'"actions"\s*:\s*\[\s*[\{"]')
_SAY_KEY = re.compile(r'"say"\s*:\s*"')
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}


class SayStreamer:
    """feed(du texte qui arrive) -> nouveau morceau de texte lisible (ou '')."""

    def __init__(self) -> None:
        self.buf = ""            # tout ce qui a été reçu jusqu'ici (pour la décision actions vide/non-vide)
        self.can_stream: bool | None = None   # None = pas encore décidé, True/False = tranché
        self._in_string = False
        self._start = -1         # position dans buf juste après le " ouvrant de "say"
        self._cursor = -1        # jusqu'où on a déjà lu à l'intérieur de la chaîne
        self._pending_escape = False
        self.done = False        # le champ "say" s'est refermé

    def feed(self, chunk: str) -> str:
        if not chunk or self.done:
            return ""
        self.buf += chunk
        if self.can_stream is None:
            if _NONEMPTY_ACTIONS.search(self.buf):
                self.can_stream = False
            elif _EMPTY_ACTIONS.search(self.buf):
                self.can_stream = True
        if not self.can_stream:
            return ""
        if not self._in_string:
            m = _SAY_KEY.search(self.buf)
            if not m:
                return ""
            self._in_string = True
            self._cursor = m.end()
        out = []
        i = self._cursor
        n = len(self.buf)
        while i < n:
            ch = self.buf[i]
            if self._pending_escape:
                if ch == "u":
                    if i + 5 > n:                         # \uXXXX coupé entre deux morceaux : on attend la suite
                        break
                    try:
                        out.append(chr(int(self.buf[i + 1:i + 5], 16)))
                    except ValueError:
                        pass
                    i += 5
                else:
                    out.append(_ESCAPES.get(ch, ch))
                    i += 1
                self._pending_escape = False
                continue
            if ch == "\\":
                self._pending_escape = True
                i += 1
                continue
            if ch == '"':
                self.done = True
                i += 1
                break
            out.append(ch)
            i += 1
        self._cursor = i
        return "".join(out)
