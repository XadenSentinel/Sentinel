"""Contrôle de Discord par raccourcis clavier globaux simulés.

Discord ne permet pas de LIRE l'état du micro sans API : l'action « Activer /
désactiver le micro » est une bascule. Sentinel mémorise donc l'état qu'il
suppose (micro actif au démarrage). Si tu changes l'état à la main, dis
« bascule le micro » ou utilise le bouton de resynchronisation de l'onglet
Discord.
"""
from __future__ import annotations

import logging

from .keyboard import send_combo
from ..replies import R

log = logging.getLogger("sentinel.discord")


class DiscordController:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.muted = False
        self.deafened = False

    def reset_state(self) -> None:
        self.muted = False
        self.deafened = False

    def _send(self, action: str) -> str | None:
        """Envoie le raccourci configuré. Retourne un message d'erreur ou None."""
        combo = (self.cfg["discord_keys"].get(action) or "").strip()
        if not combo:
            return R(self.cfg, "discord_no_key")
        try:
            send_combo(combo)
        except Exception as exc:
            log.exception("échec de l'envoi du raccourci %s", combo)
            return R(self.cfg, "discord_key_error", err=exc)
        return None

    def test(self, action: str) -> str:
        return self._send(action) or R(self.cfg, "discord_test")

    def set_mute(self, mute: bool) -> str:
        if mute == self.muted:
            return R(self.cfg, "discord_already_muted" if mute else "discord_already_active")
        err = self._send("toggle_mute")
        if err:
            return err
        self.muted = mute
        return R(self.cfg, "discord_muted" if mute else "discord_unmuted")

    def toggle_mute(self) -> str:
        err = self._send("toggle_mute")
        if err:
            return err
        self.muted = not self.muted
        return R(self.cfg, "discord_muted" if self.muted else "discord_unmuted")

    def set_deafen(self, on: bool) -> str:
        if on == self.deafened:
            return R(self.cfg, "deafen_already_on" if on else "deafen_already_off")
        err = self._send("toggle_deafen")
        if err:
            return err
        self.deafened = on
        return R(self.cfg, "deafen_on" if on else "deafen_off")

    def leave_voice(self) -> str:
        err = self._send("leave_voice")
        if err:
            return err
        self.reset_state()
        return R(self.cfg, "discord_leave")
