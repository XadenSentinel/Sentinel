"""Apprendre de ses erreurs.

Quand Sentinel comprend de travers, tu cliques sur « ✗ Mal compris » et tu dis ce que tu voulais. Il retient :
  1. une CORRECTION : la prochaine fois que tu dis (à peu près) la même phrase, il applique directement
     ce que tu voulais dire — sans passer par le raisonnement, donc instantané et fiable ;
  2. il montre aussi ces corrections au cerveau IA comme exemples de TON vocabulaire, ce qui l'aide sur
     les phrases voisines (« ouvre Steam », « lance Steam s'il te plaît »…).
Le bouton « ✓ Bien compris » garde en plus, comme exemple positif, ce que l'IA avait fait.
Tout est stocké en local (%APPDATA%\\Sentinel\\learned.json) et modifiable dans l'onglet Commandes.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from difflib import SequenceMatcher

from .config import data_dir
from .nlu import Intent, clean

log = logging.getLogger("sentinel.learning")

MAX_ITEMS = 300
FIX_MATCH = 0.9                # similarité minimale pour appliquer une correction directement

LABELS = {
    "music": "Musique", "open_app": "Ouvrir une appli", "close_app": "Fermer une appli", "open_path": "Ouvrir un dossier/fichier",
    "web": "Recherche web", "open_url": "Ouvrir un site", "volume_set": "Régler le volume", "volume_rel": "Volume +/-",
    "volume_mute": "Couper/remettre le son", "volume_get": "Dire le volume", "media": "Contrôle média", "timer_set": "Minuteur",
    "weather": "Météo", "time": "Heure", "date": "Date", "type_text": "Taper du texte", "press_keys": "Raccourci clavier",
    "ui_click": "Cliquer", "focus_window": "Changer de fenêtre", "scroll": "Défiler", "window_close": "Fermer la fenêtre",
    "tab_close": "Fermer l'onglet", "sleep": "Mise en veille", "lock": "Verrouiller", "screenshot": "Capture d'écran",
    "unknown": "Pas compris", "smalltalk": "Discussion", "wait": "Attendre",
}


def describe(it: Intent) -> str:
    """« Musique → life de damso »"""
    label = LABELS.get(it.name, it.name)
    main = next((str(v) for v in it.args.values() if v not in (None, "", False)), "")
    return f"{label} → {main[:50]}" if main else label


class LearnedMemory:
    def __init__(self) -> None:
        self._path = data_dir() / "learned.json"
        self._lock = threading.RLock()
        self.items: list[dict] = []
        try:
            self.items = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("learned.json illisible : mémoire vide")

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items[-MAX_ITEMS:], ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("mémoire d'apprentissage non enregistrée", exc_info=True)

    # ------------------------------------------------------------------ écriture
    def add_fix(self, heard: str, meant: str) -> None:
        key = clean(heard)
        if not key or not meant.strip():
            return
        with self._lock:
            self.items = [i for i in self.items if not (i["kind"] == "fix" and i["key"] == key)]
            self.items.append({"kind": "fix", "heard": heard.strip(), "key": key, "meant": meant.strip(), "ts": int(time.time())})
            self._save()

    def add_example(self, heard: str, actions: list[dict], say: str) -> None:
        key = clean(heard)
        if not key or not actions:
            return
        with self._lock:
            self.items = [i for i in self.items if not (i["kind"] == "ok" and i["key"] == key)]
            self.items.append({"kind": "ok", "heard": heard.strip(), "key": key, "actions": actions, "say": say, "ts": int(time.time())})
            self._save()

    def remove(self, ts: int) -> None:
        with self._lock:
            self.items = [i for i in self.items if i.get("ts") != ts]
            self._save()

    def clear(self) -> None:
        with self._lock:
            self.items = []
            self._save()

    # ------------------------------------------------------------------ lecture
    def lookup(self, text: str) -> str | None:
        """Correction apprise pour cette phrase (ou une quasi identique), sinon None."""
        key = clean(text)
        if not key:
            return None
        best, best_score = None, 0.0
        with self._lock:
            for item in self.items:
                if item["kind"] != "fix":
                    continue
                score = 1.0 if item["key"] == key else SequenceMatcher(None, item["key"], key).ratio()
                if score > best_score:
                    best, best_score = item, score
        return best["meant"] if best and best_score >= FIX_MATCH else None

    def examples(self, text: str, k: int = 5) -> list[dict]:
        """Les exemples les plus proches de la phrase, pour le cerveau IA."""
        key = clean(text)
        if not key:
            return []
        with self._lock:
            scored = [(SequenceMatcher(None, i["key"], key).ratio(), i) for i in self.items]
        scored = [s for s in scored if s[0] >= 0.42]
        scored.sort(key=lambda s: (s[0], s[1].get("ts", 0)), reverse=True)
        return [i for _, i in scored[:k]]

    def prompt_block(self, text: str) -> str:
        lines = []
        for i in self.examples(text):
            if i["kind"] == "fix":
                lines.append(f"- Quand il dit « {i['heard']} », il veut dire : « {i['meant']} ».")
            else:
                lines.append(f"- « {i['heard']} » → {json.dumps({'actions': i['actions'], 'say': i.get('say', '')}, ensure_ascii=False)}")
        return ("\nCorrections et exemples appris de CET utilisateur (ils priment sur le reste) :\n" + "\n".join(lines) + "\n") if lines else ""
