"""Description des réglages affichés dans les pages de l'interface web.

Chaque champ a un type qui sert à la fois à dessiner le formulaire et à VÉRIFIER la valeur reçue :
la page ne peut modifier que les clés listées ici, avec des valeurs du bon type et dans les bonnes limites.
"""
from __future__ import annotations

from ..asr import WHISPER_MODELS
from ..permissions import FAMILIES, SENSITIVE
from ..replies import STYLES
from ..tts import EDGE_VOICES
from ..ui.theme import ACCENTS, THEMES, is_hex


def F(key: str, label: str, type: str = "text", **kw) -> dict:
    return {"key": key, "label": label, "type": type, **kw}


def S(title: str, fields: list, help: str = "") -> dict:
    return {"title": title, "help": help, "fields": fields}


def opts(d: dict) -> list:
    return [[k, v] for k, v in d.items()]


SEARCH_ENGINES = {"google": "Google", "duckduckgo": "DuckDuckGo", "bing": "Bing"}
PROVIDERS = {"youtube": "YouTube — lecture instantanée", "ytmusic": "YouTube Music", "spotify": "Spotify — lecture directe (compte Premium)"}
TTS_ENGINES = {"auto": "Automatique — voix neuronale, sinon Windows", "edge": "Voix neuronale Microsoft (en ligne)", "sapi": "Voix Windows (hors-ligne)"}
BRAIN_MODES = {"auto": "Automatique — les règles d'abord, l'IA si je ne comprends pas", "always": "Toujours l'IA (plus intelligent, un peu plus lent)"}
BRAIN_BACKENDS = {"ollama": "Ollama (recommandé, gratuit)", "openai": "Serveur compatible OpenAI (LM Studio…)",
                  "anthropic": "Claude — API Anthropic (le plus intelligent, payant à l'usage)"}
UI_MODES = {"web": "Nouvelle interface web", "classic": "Ancienne interface"}

_CONFIRM_FAMILIES = sorted(set(SENSITIVE.values()))
def _permission_fields() -> list:
    fields = []
    for fam, spec in FAMILIES.items():
        fields.append(F(f"permissions.{fam}_enabled", spec["label"], "bool"))
    for fam in _CONFIRM_FAMILIES:
        fields.append(F(f"permissions.{fam}_confirm", "Demander confirmation : " + FAMILIES[fam]["label"].lower(), "bool"))
    return fields

PAGES: dict[str, dict] = {
    "commands": {"title": "Commandes", "sections": [
        S("Mes raccourcis vocaux (macros)", [F("shortcuts", "", "dict", kph="Phrase (ex. mode jeu)", vph="Commande(s) séparées par ;  ex. coupe le son ; lance fortnite")],
          "Une phrase déclenche une ou plusieurs commandes. Utile aussi pour les phrases que Sentinel comprend mal : ajoute-les telles qu'il les entend."),
        S("Corrections vocales", [F("corrections", "", "dict", kph="Ce que Sentinel entend (ex. dans so)", vph="Ce que tu veux dire (ex. damso)")],
          "Remplace automatiquement un mot mal reconnu par le bon."),
    ]},
    "apps": {"title": "Applis et PC", "sections": [
        S("Accès à l'ordinateur", [
            F("scan_full_disk", "Analyser tous les disques", "bool", help="Sinon : seulement les dossiers usuels."),
            F("scan_extra_paths", "Dossiers en plus", "list", ph="ex. D:\\Jeux, E:\\Logiciels", help="Séparés par des virgules."),
            F("allow_scripts", "Autoriser l'ouverture de scripts (.bat, .ps1…)", "bool", help="Déconseillé : Sentinel refuse les scripts par sécurité."),
        ], "Sentinel ouvre les programmes, dossiers et fichiers comme un double-clic. Il ne désactive aucune protection de Windows et ne supprime ni ne déplace rien."),
        S("Mes alias (prioritaires)", [F("app_aliases", "", "dict", kph="Nom prononcé (ex. fortnite)", vph="Chemin .exe / lien steam:// / URL / commande")]),
    ]},
    "music": {"title": "Musique", "sections": [
        S("Lecture", [F("music_provider", "Source de lecture", "select", options=opts(PROVIDERS)),
                      F("music_radio", "Mode radio pour « mets du… »", "bool", help="Enchaîne les titres de l'artiste.")]),
        S("Spotify — lecture directe", [F("spotify_client_id", "Client ID Spotify", "text", ph="ex. 3f9a…")]),
        S("Mes playlists", [F("playlists", "", "dict", kph="Nom (ex. rap fr)", vph="Lien YouTube / YouTube Music / Spotify")]),
    ]},
    "discord": {"title": "Discord", "sections": [
        S("Raccourcis clavier", [
            F("discord_keys.toggle_mute", "Micro (activer / couper)", "text", test="toggle_mute", ph="ex. ctrl+alt+f9"),
            F("discord_keys.toggle_deafen", "Sourdine du casque", "text", test="toggle_deafen", ph="ex. ctrl+alt+f10"),
            F("discord_keys.leave_voice", "Quitter le salon vocal", "text", test="leave_voice", ph="ex. ctrl+alt+f11"),
        ]),
    ]},
    "brain": {"title": "Cerveau IA", "sections": [
        S("Comportement", [F("brain_enabled", "Activer le cerveau IA", "bool"),
                           F("brain_mode", "Quand l'utiliser", "select", options=opts(BRAIN_MODES)),
                           F("follow_up", "Continuer d'écouter après une réponse de l'IA", "bool", help="Conversation sans redire le mot déclencheur.")]),
        S("Modèle", [F("brain_backend", "Serveur", "select", options=opts(BRAIN_BACKENDS)),
                     F("brain_url", "Adresse (Ollama / LM Studio)", "text", ph="http://127.0.0.1:11434"),
                     F("brain_api_key", "Clé API (Claude, ou serveur OpenAI)", "secret", ph="sk-ant-…"),
                     F("brain_model", "Modèle utilisé", "select", options_from="models")]),
    ]},
    "voice": {"title": "Voix et écoute", "sections": [
        S("Voix de Sentinel", [
            F("tts_enabled", "Réponses vocales", "bool"),
            F("tts_engine", "Moteur vocal", "select", options=opts(TTS_ENGINES)),
            F("tts_edge_voice", "Voix neuronale", "select", options=opts(EDGE_VOICES)),
            F("tts_pitch", "Hauteur de la voix", "int", min=-20, max=20, step=1, unit=" Hz"),
            F("tts_rate", "Vitesse", "int", min=-5, max=5, step=1),
            F("tts_volume", "Volume de la voix", "int", min=0, max=100, step=5, unit=" %"),
            F("tts_voice", "Voix Windows de secours (sans Internet)", "select", options_from="voices"),
        ], "La voix neuronale (Microsoft Edge, gratuite) est bien plus naturelle mais demande Internet. Sans connexion, Sentinel bascule seul sur la voix Windows."),
        S("Écoute", [
            F("wake_word", "Mot déclencheur", "text"),
            F("wake_aliases", "Variantes reconnues", "list", help="Séparées par des virgules."),
            F("listen_timeout", "Durée d'écoute après le mot seul", "int", min=3, max=15, step=1, unit=" s"),
            F("mic_device", "Microphone", "select", options_from="mics"),
            F("show_heard", "Journaliser tout ce qui est entendu", "bool", help="Utile pour régler les variantes."),
            F("asr_whisper", "Reconnaissance de précision (Whisper)", "bool", help="Demande « pip install faster-whisper » ; le modèle se télécharge une fois."),
            F("whisper_model", "Modèle Whisper", "select", options=opts(WHISPER_MODELS)),
        ]),
        S("Confort d'écoute", [
            F("wake_sound", "Petit son quand Sentinel te reconnaît", "bool"),
            F("barge_in", "Interrompre Sentinel si tu parles par-dessus", "bool",
              help="Fonctionne mieux avec un casque : au haut-parleur, Sentinel peut parfois s'interrompre en s'entendant lui-même."),
            F("brain_stream", "Commencer à parler dès la première phrase de l'IA", "bool", help="Uniquement pour une discussion, jamais avant qu'une action ait fini."),
            F("dnd", "Mode silencieux (n'agit pas moins, mais ne parle plus)", "bool"),
        ]),
    ]},
    "replies": {"title": "Réponses", "sections": [
        S("Style de Sentinel", [F("reply_style", "Style de réponse", "select", options=opts(STYLES)),
                                F("user_name", "Comment Sentinel t'appelle", "text", ph="prénom, « monsieur »… (vide = rien)")]),
    ]},
    "settings": {"title": "Paramètres", "sections": [
        S("Général", [
            F("weather_city", "Ville pour la météo", "text", ph="ex. Lille"),
            F("search_engine", "Moteur de recherche web", "select", options=opts(SEARCH_ENGINES)),
            F("volume_step", "Pas du volume", "int", min=1, max=30, step=1, unit=" %"),
            F("brightness_step", "Pas de la luminosité", "int", min=1, max=30, step=1, unit=" %"),
            F("start_with_windows", "Lancer Sentinel au démarrage de Windows", "bool"),
            F("minimize_to_tray", "Réduire dans la zone de notification (ancienne interface)", "bool"),
        ]),
        S("Apparence", [
            F("assistant_name", "Nom de l'assistant", "text", ph="vide = le mot déclencheur"),
            F("theme", "Thème (couleurs du fond)", "select", options=[[k, k] for k in THEMES]),
            F("custom_bg", "Couleur de fond libre", "color", help="Sombre de préférence. Remplace le thème."),
            F("accent", "Couleur d'accent", "select", options=[[k, k] for k in ACCENTS]),
            F("custom_accent", "Couleur d'accent libre", "color", help="Remplace la couleur d'accent ci-dessus."),
            F("sphere_density", "Densité de la sphère", "int", min=400, max=4000, step=100),
            F("hud_fx", "Effets (balayage lumineux, lueurs)", "bool"),
            F("skip_intro", "Passer l'écran de démarrage", "bool"),
        ]),
        S("Interface", [F("ui", "Interface au prochain démarrage", "select", options=opts(UI_MODES))]),
        S("Mises à jour", [F("update_check", "Chercher une mise à jour au démarrage (une fois par jour)", "bool")]),
    ]},
    "permissions": {"title": "Permissions", "sections": [
        S("Familles d'actions", _permission_fields(),
          "Désactive une famille pour empêcher Sentinel de faire ce type d'action, à la voix comme via l'IA. "
          "Les cases « Demander confirmation » ajoutent une question orale avant les actions les plus sensibles "
          "(fermer une appli, mettre en veille, verrouiller, quitter un salon Discord) : Sentinel demande, "
          "et n'agit que si tu réponds « oui »."),
    ]},
}

FIELDS: dict[str, dict] = {f["key"]: f for page in PAGES.values() for sec in page["sections"] for f in sec["fields"]}
SECRETS = {k for k, f in FIELDS.items() if f["type"] == "secret"}


# ---------------------------------------------------------------------- lecture / validation
def get_value(cfg, key: str):
    if "." in key:
        base, sub = key.split(".", 1)
        return (cfg[base] or {}).get(sub, "")
    return cfg[key]


def public_value(cfg, field: dict):
    """Valeur envoyée à la page (les secrets ne sortent jamais)."""
    v = get_value(cfg, field["key"])
    t = field["type"]
    if t == "secret":
        return {"set": bool(v)}
    if t == "list":
        return list(v or [])
    if t == "select" and field["key"] == "mic_device":
        return "" if v is None else str(v)
    return v


def coerce(field: dict, value, allowed: list | None = None):
    """Vérifie et convertit une valeur reçue. Lève ValueError si elle est invalide."""
    t = field["type"]
    if t == "bool":
        if not isinstance(value, bool):
            raise ValueError("oui / non attendu")
        return value
    if t == "int":
        try:
            v = int(float(value))
        except (TypeError, ValueError):
            raise ValueError("nombre attendu") from None
        return max(field["min"], min(field["max"], v))
    if t in ("text", "secret"):
        v = str(value if value is not None else "").strip()
        if len(v) > 300:
            raise ValueError("texte trop long")
        return v
    if t == "color":
        v = str(value or "").strip()
        if v and not is_hex(v):
            raise ValueError("couleur #RRGGBB attendue")
        return v
    if t == "list":
        if isinstance(value, str):
            value = [p for p in value.split(",")]
        if not isinstance(value, list) or len(value) > 50:
            raise ValueError("liste invalide")
        return [str(p).strip() for p in value if str(p).strip()][:50]
    if t == "dict":
        if not isinstance(value, dict) or len(value) > 300:
            raise ValueError("tableau invalide")
        out = {}
        for k, v in value.items():
            k, v = str(k).strip(), str(v).strip()
            if k and len(k) <= 120 and len(v) <= 600:
                out[k] = v
        return out
    if t == "select":
        valid = [o[0] for o in (allowed if allowed is not None else field.get("options", []))]
        v = "" if value is None else str(value)
        if valid and v not in valid:
            raise ValueError("choix inconnu")
        return v
    raise ValueError("type inconnu")
