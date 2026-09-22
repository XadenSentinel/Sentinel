"""Permissions par famille d'actions, avec confirmation vocale pour les plus sensibles.

Chaque famille peut être désactivée : Sentinel refuse alors ces actions, qu'elles viennent d'une
commande classique ou du cerveau IA. Certaines actions (fermer une appli, mettre en veille…) peuvent
en plus demander une confirmation : Sentinel pose la question et n'agit que si tu réponds « oui ».
"""
from __future__ import annotations

FAMILIES: dict[str, dict] = {
    "files":    {"label": "Fichiers et dossiers",             "intents": {"open_path"}},
    "keyboard": {"label": "Clavier (taper du texte, raccourcis)", "intents": {"type_text", "press_keys", "scroll"}},
    "clicks":   {"label": "Cliquer dans les applications",     "intents": {"ui_click"}},
    "web":      {"label": "Ouvrir des sites web",              "intents": {"open_url", "web", "focus_window"}},
    "apps":     {"label": "Lancer et fermer des applications", "intents": {"open_app", "close_app"}},
    "windows":  {"label": "Fenêtres et onglets",                "intents": {"window_close", "tab_close"}},
    "power":    {"label": "Veille et verrouillage du PC",       "intents": {"sleep", "lock"}},
    "discord":  {"label": "Discord",                            "intents": {"discord_mute", "discord_toggle", "discord_deafen", "discord_leave"}},
}

# Actions qui peuvent demander une confirmation vocale (-> famille propriétaire).
SENSITIVE = {
    "close_app": "apps", "sleep": "power", "lock": "power",
    "window_close": "windows", "tab_close": "windows", "discord_leave": "discord",
}

_INTENT_TO_FAMILY = {intent: fam for fam, spec in FAMILIES.items() for intent in spec["intents"]}

DEFAULTS: dict[str, bool] = {}
for _fam in FAMILIES:
    DEFAULTS[f"{_fam}_enabled"] = True
for _intent, _fam in SENSITIVE.items():
    DEFAULTS.setdefault(f"{_fam}_confirm", _fam in ("apps", "power", "discord"))


def family_of(intent: str) -> str | None:
    return _INTENT_TO_FAMILY.get(intent)


def family_enabled(cfg, intent: str) -> bool:
    fam = family_of(intent)
    if fam is None:
        return True
    return bool(cfg["permissions"].get(f"{fam}_enabled", True))


def confirm_needed(cfg, intent: str) -> bool:
    fam = SENSITIVE.get(intent)
    if fam is None:
        return False
    return bool(cfg["permissions"].get(f"{fam}_confirm", False))
