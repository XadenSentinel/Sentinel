"""Toutes les phrases prononcées par Sentinel, en un seul endroit.

- 3 styles : « jarvis » (formel, vouvoiement), « cool » (tutoiement), « court » (le strict minimum) ;
- plusieurs variantes par phrase : Sentinel en tire une au hasard ;
- chaque phrase peut être remplacée par la tienne (page « Réponses » de l'interface,
  réglage `custom_replies`). Plusieurs variantes = sépare-les par « | ».

Variables utilisables dans une phrase : {appel} (« , Enzo » ou rien, selon ton prénom)
plus celles propres à chaque phrase (ex. {p} pour un pourcentage).
"""
from __future__ import annotations

import datetime
import logging
import random
import threading

log = logging.getLogger("sentinel.replies")

STYLES = {
    "jarvis": "Jarvis — formel, vouvoiement",
    "cool": "Décontracté — tutoiement",
    "court": "Court — le strict minimum",
}

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]


def fr_date(d: datetime.date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def fr_time(now: datetime.datetime) -> str:
    return f"{now.hour} heures {now.minute:02d}" if now.minute else f"{now.hour} heures pile"


# clé -> (libellé dans l'interface ou "" si masquée, variables, {style: [variantes]})
def _e(label: str, args: tuple, jarvis, cool=None, court=None) -> tuple:
    def lst(x):
        return [x] if isinstance(x, str) else list(x)
    styles = {"jarvis": lst(jarvis)}
    if cool is not None:
        styles["cool"] = lst(cool)
    if court is not None:
        styles["court"] = lst(court)
    return (label, args, styles)


CATALOG: dict[str, tuple] = {
    # ------------------------------------------------------------ général
    "ack": _e("Quand j'entends « Sentinel »", (),
              ["Oui{appel} ?", "Je vous écoute{appel}.", "À votre service{appel}.", "Je suis là{appel}."],
              ["Yep ?", "Je t'écoute.", "Ouais{appel} ?", "Dis-moi{appel}."],
              ["Oui ?", "Oui."]),
    "done": _e("Action terminée (générique)", (),
               ["C'est fait{appel}.", "Fait{appel}."], ["C'est fait !", "Voilà."], "Fait."),
    "unknown": _e("Phrase non comprise", ("heard",),
                  "Je n'ai pas compris « {heard} »{appel}.",
                  ["Hmm, j'ai entendu « {heard} » mais je vois pas ce que tu veux.",
                   "J'ai pas compris « {heard} »."],
                  "Pas compris : {heard}."),
    "error": _e("Erreur pendant une action", (),
                "Une erreur est survenue pendant l'exécution{appel}.", "Aïe, ça a planté.", "Erreur."),
    "quit": _e("Quand je le ferme", (),
               "Extinction des systèmes. À bientôt{appel}.", "Ok, à plus !", "Au revoir."),
    "hello": _e("Quand je dis bonjour", (),
                ["Bonjour{appel}. Que puis-je faire pour vous ?", "Bonjour{appel}."],
                ["Salut{appel} !", "Hey{appel} !"], "Salut."),
    "thanks": _e("Quand je dis merci", (),
                 ["Avec plaisir{appel}.", "Je vous en prie{appel}."], ["De rien !", "Avec plaisir !"], "De rien."),
    "howareyou": _e("Quand je demande comment il va", (),
                    "Tous les systèmes sont opérationnels{appel}.", "Ça roule, et toi ?", "Ça va."),
    "whoareyou": _e("Quand je demande qui il est", (),
                    "Je suis Sentinel, votre assistant vocal.", "Moi c'est Sentinel, ton assistant vocal.", "Sentinel."),
    "help": _e("Quand je demande de l'aide", (),
               "Je gère la musique, le volume, Discord, les applications, les minuteurs, la météo, "
               "les captures d'écran et la mise en veille. La liste complète est dans l'onglet Commandes.",
               "Je m'occupe de la musique, du volume, de Discord, de tes applis, des minuteurs, de la météo, "
               "des captures et de la veille. Tout est dans l'onglet Commandes.",
               "Voir l'onglet Commandes."),
    "time": _e("Heure", ("heure",), "Il est {heure}.", "Il est {heure}.", "{heure}."),
    "date": _e("Date", ("date",), "Nous sommes {date}.", "On est {date}.", "{date}."),
    # ------------------------------------------------------------ volume
    "volume_set": _e("Volume réglé", ("p",), "Volume réglé à {p} pour cent.",
                     ["Hop, volume à {p} pour cent.", "Volume à {p} pour cent."], "{p} pour cent."),
    "volume_change": _e("", ("p",), "Volume à {p} pour cent.", "Volume à {p} pour cent.", "{p} pour cent."),
    "volume_adjusted": _e("", (), "Volume ajusté.", "Volume ajusté.", "Ok."),
    "volume_get": _e("", ("p",), "Le volume est à {p} pour cent.", "Il est à {p} pour cent.", "{p} pour cent."),
    "volume_read_error": _e("", (), "Je n'arrive pas à lire le volume.", "J'arrive pas à lire le volume.", "Volume illisible."),
    "mute_on": _e("", (), "Son coupé.", "Son coupé.", "Muet."),
    "mute_off": _e("", (), "Son rétabli.", "Son remis.", "Son."),
    "media_playpause": _e("", (), "C'est fait{appel}.", "Ok.", "Ok."),
    "media_next": _e("", (), "Titre suivant.", "Suivant !", "Suivant."),
    "media_prev": _e("", (), "Titre précédent.", "Précédent !", "Précédent."),
    # ------------------------------------------------------------ Discord
    "discord_muted": _e("Micro coupé (Discord)", (), "Micro coupé.", "Micro coupé.", "Muet."),
    "discord_unmuted": _e("Micro réactivé (Discord)", (), "Micro réactivé.", "C'est bon, on t'entend.", "Micro."),
    "discord_already_muted": _e("", (), "Votre micro est déjà coupé.", "Ton micro est déjà coupé.", "Déjà coupé."),
    "discord_already_active": _e("", (), "Votre micro est déjà actif.", "Ton micro est déjà actif.", "Déjà actif."),
    "deafen_on": _e("", (), "Sourdine activée.", "Sourdine activée.", "Sourdine."),
    "deafen_off": _e("", (), "Sourdine désactivée.", "Sourdine retirée.", "Sourdine off."),
    "deafen_already_on": _e("", (), "Le casque est déjà en sourdine.", "Le casque est déjà en sourdine.", "Déjà en sourdine."),
    "deafen_already_off": _e("", (), "Le casque est déjà actif.", "Le casque est déjà actif.", "Déjà actif."),
    "discord_leave": _e("", (), "Je quitte le salon vocal.", "Je quitte le vocal.", "Je quitte."),
    "discord_no_key": _e("", (), "Aucun raccourci n'est configuré pour cette action.",
                         "Y a pas de raccourci configuré pour ça.", "Pas de raccourci."),
    "discord_key_error": _e("", ("err",), "Je n'ai pas pu envoyer le raccourci : {err}",
                            "J'ai pas pu envoyer le raccourci : {err}", "Échec du raccourci."),
    "discord_test": _e("", (), "Raccourci envoyé.", "Raccourci envoyé.", "Envoyé."),
    # ------------------------------------------------------------ musique
    "music_ask": _e("", (), "Que souhaitez-vous écouter ?", "Tu veux écouter quoi ?", "Quoi ?"),
    "music_unknown_playlist": _e("", ("playlist",),
                                 "Je ne connais pas la playlist {playlist}, je cherche directement.",
                                 "Je connais pas la playlist {playlist}, je cherche direct.", "Playlist inconnue."),
    "music_play": _e("Lancement d'un titre", ("title",), "Je lance {title}.",
                     ["C'est parti pour {title}.", "Je mets {title}."], "{title}."),
    "music_spotify_search": _e("", ("query",), "J'ouvre la recherche {query} dans Spotify.",
                               "J'ouvre {query} dans Spotify.", "Spotify : {query}."),
    "music_fallback": _e("", ("query",), "Je n'ai pas pu lancer directement, j'ouvre la recherche {query}.",
                         "J'ai pas pu lancer direct, j'ouvre la recherche {query}.", "Recherche {query}."),
    "music_spotify_playlist": _e("", ("name",), "J'ouvre la playlist {name} dans Spotify.",
                                 "J'ouvre la playlist {name} dans Spotify.", "Playlist {name}."),
    "music_playlist": _e("", ("name",), "J'ouvre la playlist {name}.", "J'ouvre la playlist {name}.", "Playlist {name}."),
    "music_playlist_track": _e("", ("title", "name"), "Je lance {title} depuis la playlist {name}.",
                               "Je lance {title} de la playlist {name}.", "{title}."),
    "music_track_missing": _e("", ("query",), "Je ne trouve pas {query} dans cette playlist.",
                              "Je trouve pas {query} dans cette playlist.", "{query} introuvable."),
    # ------------------------------------------------------------ applications
    "app_ask": _e("", (), "Quelle application dois-je lancer ?", "Tu veux que je lance quoi ?", "Quoi ?"),
    "app_missing": _e("", ("name",), "Je ne trouve pas {name}. Ajoutez-la dans l'onglet Applications.",
                      "Je trouve pas {name}. Ajoute-la dans l'onglet Applications.", "{name} introuvable."),
    "app_fail": _e("", ("name", "err"), "Je n'ai pas réussi à lancer {name}.", "J'ai pas réussi à lancer {name}.", "Échec."),
    "app_open": _e("Lancement d'une application", ("name",), "Je lance {name}.",
                   ["Je lance {name}.", "{name}, c'est parti."], "{name}."),
    "web": _e("Recherche web", ("query",), "Je cherche {query}.", "Je cherche {query}.", "Recherche."),
    # ------------------------------------------------------------ PC
    "close_ask": _e("", (), "Quelle application dois-je fermer ?", "Tu veux que je ferme quoi ?", "Quoi ?"),
    "close_app": _e("Fermeture d'une application", ("name",), "Je ferme {name}.", "Je ferme {name}.", "{name} fermé."),
    "close_none": _e("", ("name",), "{name} ne semble pas ouvert.", "{name} a l'air pas ouvert.", "{name} n'est pas ouvert."),
    "close_refused": _e("", ("name",), "{name} refuse de se fermer. Dites « tue {name} » pour forcer.",
                        "{name} ne veut pas se fermer. Dis « tue {name} » pour forcer.", "Refusé. Dis « tue {name} »."),
    "close_protected": _e("", ("name",), "Je préfère ne pas fermer {name}.", "Je préfère pas fermer {name}.", "Non."),
    "close_window": _e("", (), "Fenêtre fermée.", "Fermée.", "Fermée."),
    "tab_close": _e("", (), "Onglet fermé.", "Onglet fermé.", "Fermé."),
    "sleep": _e("Mise en veille du PC", (), "Mise en veille dans quelques secondes. À tout à l'heure{appel}.",
                "Je mets le PC en veille. À plus !", "Veille."),
    "lock": _e("", (), "Session verrouillée.", "C'est verrouillé.", "Verrouillé."),
    "screenshot": _e("Capture d'écran", (), "Capture d'écran enregistrée dans vos images.",
                     "Capture faite, elle est dans tes images.", "Capture faite."),
    "screenshot_fail": _e("", (), "Je n'ai pas pu prendre la capture d'écran.", "J'ai pas pu faire la capture.", "Échec."),
    "window_switch": _e("", (), "Je change de fenêtre.", "Je change de fenêtre.", "Ok."),
    "desktop": _e("", (), "Voici le bureau.", "Voilà le bureau.", "Bureau."),
    "brightness_set": _e("Luminosité réglée", ("p",), "Luminosité réglée à {p} pour cent.",
                         "Luminosité à {p} pour cent.", "{p} pour cent."),
    "brightness_change": _e("", ("p",), "Luminosité à {p} pour cent.", "Luminosité à {p} pour cent.", "{p} pour cent."),
    "brightness_get": _e("", ("p",), "La luminosité est à {p} pour cent.", "Elle est à {p} pour cent.", "{p} pour cent."),
    "brightness_unsupported": _e("", (), "Je ne peux pas régler la luminosité de cet écran.",
                                 "Je peux pas régler la luminosité de cet écran.", "Impossible."),
    # ------------------------------------------------------------ minuteurs
    "timer_set": _e("Minuteur lancé", ("duree",), "C'est parti : minuteur de {duree}.",
                    ["Minuteur de {duree} lancé.", "C'est parti pour {duree}."], "{duree}."),
    "timer_set_label": _e("", ("duree", "label"), "Minuteur de {duree} pour {label}.",
                          "Minuteur de {duree} pour {label}.", "{duree}, {label}."),
    "timer_done": _e("Minuteur terminé", ("duree",), "Votre minuteur de {duree} est terminé{appel}.",
                     ["C'est l'heure ! Les {duree} sont écoulées.", "Minuteur de {duree} terminé !"], "Terminé."),
    "timer_done_label": _e("Minuteur terminé (avec un nom)", ("duree", "label"),
                           "C'est l'heure : {label}.", "Ding ! {label}.", "{label}."),
    "alarm_set": _e("Réveil réglé", ("heure",), "Réveil réglé à {heure}.", "Réveil réglé à {heure}.", "Réveil, {heure}."),
    "alarm_done": _e("Sonnerie du réveil", (), "Il est l'heure de vous réveiller{appel}.",
                     "Debout{appel} ! C'est l'heure !", "Réveil."),
    "timer_left": _e("", ("reste",), "Il reste {reste}.", "Il reste {reste}.", "{reste}."),
    "timer_left_many": _e("", ("n", "reste"), "Vous avez {n} minuteurs. Le prochain se termine dans {reste}.",
                          "T'as {n} minuteurs. Le prochain finit dans {reste}.", "{n} minuteurs, {reste}."),
    "timer_none": _e("", (), "Aucun minuteur en cours.", "Y a pas de minuteur en cours.", "Aucun."),
    "timer_cancel": _e("", (), "Minuteur annulé.", "Minuteur annulé.", "Annulé."),
    "timer_cancel_many": _e("", ("n",), "{n} minuteurs annulés.", "{n} minuteurs annulés.", "{n} annulés."),
    "timer_ask": _e("", (), "Pour combien de temps ?", "Pour combien de temps ?", "Combien ?"),
    # ------------------------------------------------------------ météo
    "weather": _e("Météo du jour", ("ville", "temp", "desc", "tmax", "tmin"),
                  "À {ville}, il fait {temp} degrés, {desc}. Maximum {tmax}, minimum {tmin}.",
                  "À {ville} il fait {temp} degrés, {desc}. Entre {tmin} et {tmax} aujourd'hui.",
                  "{temp} degrés, {desc}."),
    "weather_rain": _e("", ("pluie",), "Risque de pluie : {pluie} pour cent.", "{pluie} pour cent de risque de pluie.", "Pluie {pluie} pour cent."),
    "weather_tomorrow": _e("Météo de demain", ("ville", "desc", "tmax", "tmin"),
                           "Demain à {ville} : {desc}, de {tmin} à {tmax} degrés.",
                           "Demain à {ville} : {desc}, entre {tmin} et {tmax} degrés.",
                           "Demain : {desc}, {tmax} degrés."),
    "weather_no_city": _e("", (), "Indiquez votre ville dans les paramètres, section Actions.",
                          "Mets ta ville dans les paramètres, section Actions.", "Ville manquante."),
    "weather_error": _e("", (), "Je n'arrive pas à joindre le service météo.", "J'arrive pas à joindre la météo.", "Météo indisponible."),
    # ------------------------------------------------------------ fichiers / dossiers
    "path_ask": _e("", (), "Quel dossier ou quel fichier dois-je ouvrir ?", "Tu veux ouvrir quoi ?", "Quoi ?"),
    "path_open": _e("Ouverture d'un dossier / fichier", ("name",), "J'ouvre {name}.", "J'ouvre {name}.", "{name}."),
    "path_missing": _e("", ("name",), "Je ne trouve pas {name} sur votre ordinateur.",
                       "Je trouve pas {name} sur ton PC.", "{name} introuvable."),
    "path_blocked": _e("", ("name",), "Je préfère ne pas exécuter {name} : c'est un script.",
                       "Je préfère pas lancer {name}, c'est un script.", "Bloqué."),
    # ------------------------------------------------------------ interaction avec les applications
    "win_focus": _e("Passage à une autre fenêtre", ("name",), "Je passe sur {name}.", "Go sur {name}.", "{name}."),
    "win_missing": _e("", ("name",), "Je ne trouve aucune fenêtre « {name} » ouverte.", "Je vois pas de fenêtre « {name} ».", "Fenêtre introuvable."),
    "interact_blocked": _e("", (), "Par sécurité, je ne tape rien dans un terminal ou une fenêtre système.",
                           "Par sécurité je tape rien dans un terminal.", "Bloqué par sécurité."),
    "key_refused": _e("", (), "Ce raccourci ne fait pas partie de ceux que j'ai le droit d'utiliser.",
                      "Ce raccourci, j'ai pas le droit.", "Raccourci refusé."),
    "ui_click_done": _e("Clic sur un bouton", ("name",), "Je clique sur {name}.", "Clic sur {name}.", "{name}."),
    "ui_notfound": _e("", ("name",), "Je ne trouve pas « {name} » dans la fenêtre active.", "Je trouve pas « {name} » ici.", "Introuvable."),
    "ui_missing": _e("", (), "Pour cliquer dans les applications, il faut installer le module uiautomation : pip install uiautomation.",
                     "Il faut installer uiautomation pour que je clique : pip install uiautomation.", "Module uiautomation absent."),
    "ui_refused": _e("", ("name",), "Je préfère ne pas cliquer sur « {name} » : c'est une action sensible. Faites-le vous-même.",
                     "Je clique pas sur « {name} », c'est sensible. Fais-le toi-même.", "Action sensible refusée."),
    "url_open": _e("Ouverture d'un site", ("name",), "J'ouvre {name}.", "J'ouvre {name}.", "{name}."),
    "url_refused": _e("", (), "Cette adresse ne me semble pas valable.", "Cette adresse a l'air bizarre.", "Adresse refusée."),
    # ------------------------------------------------------------ Spotify
    "spotify_play": _e("Lecture Spotify", ("title", "artist"), "Je lance {title} de {artist} sur Spotify.",
                       ["C'est parti pour {title} de {artist}.", "Je mets {title} de {artist}."], "{title}, {artist}."),
    "spotify_not_connected": _e("", (), "Spotify n'est pas connecté. Ouvrez l'onglet Musique pour le connecter.",
                                "Spotify est pas connecté. Va dans l'onglet Musique pour le connecter.", "Spotify non connecté."),
    "spotify_no_premium": _e("", (), "Spotify n'autorise le lancement direct qu'avec un compte Premium.",
                             "Spotify autorise le lancement direct qu'avec Premium.", "Premium requis."),
    "spotify_no_device": _e("", (), "Je n'arrive pas à joindre l'application Spotify.",
                            "J'arrive pas à joindre l'appli Spotify.", "Spotify injoignable."),
    "spotify_not_found": _e("", ("query",), "Je ne trouve pas {query} sur Spotify.",
                            "Je trouve pas {query} sur Spotify.", "{query} introuvable."),
    # ------------------------------------------------------------ cerveau IA
    "thinking": _e("Quand l'IA réfléchit longtemps", (), ["Je réfléchis{appel}.", "Une seconde{appel}."],
                   ["Hmm, laisse-moi réfléchir.", "Une seconde."], "…"),
    "brain_refuse": _e("", (), "Je préfère que vous me le demandiez explicitement pour cette action.",
                       "Je préfère que tu me le demandes clairement pour ça.", "Dis-le explicitement."),
    # ------------------------------------------------------------ permissions et mémoire
    "perm_refused": _e("", (), "Cette action est désactivée dans les Permissions.",
                       "Cette action est désactivée dans Permissions.", "Désactivé."),
    "perm_confirm": _e("Avant une action sensible", ("action",), "Tu veux vraiment {action} ? Dis oui pour confirmer.",
                       "Tu veux vraiment {action} ? Dis oui.", "{action} ? Oui ?"),
    "perm_cancelled": _e("", (), "D'accord, j'annule.", "Ok, j'annule.", "Annulé."),
    "remembered": _e("Après « souviens-toi que… »", ("text",), "Je m'en souviendrai.", "Noté, je garde ça en tête.", "Noté."),
    "dnd_on": _e("Mode silencieux activé", (), "Mode silencieux activé. Je n'annonce plus rien à voix haute.",
                "Mode silencieux activé, je dis plus rien à voix haute.", "Silencieux."),
    "dnd_off": _e("Mode silencieux désactivé", (), "Mode silencieux désactivé.", "Mode silencieux désactivé.", "Voix réactivée."),
    "brain_off": _e("", (), "Mon cerveau IA n'est pas disponible. Vérifiez qu'Ollama est lancé.",
                    "Mon cerveau IA est pas dispo. Vérifie qu'Ollama est lancé.", "IA indisponible."),
    "weather_city_unknown": _e("", ("ville",), "Je ne trouve pas la ville {ville}.", "Je trouve pas la ville {ville}.", "Ville inconnue."),
}


class _SafeDict(dict):
    def __missing__(self, key):          # variable inconnue : on la laisse telle quelle
        return "{" + key + "}"


def _fmt(template: str, **kw) -> str:
    try:
        return template.format_map(_SafeDict(**kw)).strip()
    except (ValueError, IndexError):     # accolade mal formée dans une phrase perso
        return template.strip()


def variants(cfg, key: str) -> list[str]:
    """Variantes actuellement actives pour cette phrase (perso si définie, sinon style choisi)."""
    custom = (cfg["custom_replies"].get(key) or "").strip()
    if custom:
        return [v.strip() for v in custom.split("|") if v.strip()]
    entry = CATALOG.get(key)
    if entry is None:
        return [key]
    styles = entry[2]
    return styles.get(cfg["reply_style"]) or styles["jarvis"]


# Phrases qui signalent un échec / une information à dire telle quelle
FAIL_KEYS = {
    "app_missing", "app_fail", "app_ask", "close_none", "close_refused", "close_protected", "close_ask",
    "brightness_unsupported", "discord_no_key", "discord_key_error", "screenshot_fail", "weather_error",
    "weather_no_city", "weather_city_unknown", "timer_ask", "error", "unknown", "path_missing", "path_blocked",
    "path_ask", "spotify_not_connected", "spotify_no_premium", "spotify_no_device", "spotify_not_found",
    "music_ask", "music_fallback", "volume_read_error", "discord_already_muted", "discord_already_active",
    "deafen_already_on", "deafen_already_off", "win_missing", "interact_blocked", "key_refused", "ui_notfound",
    "ui_missing", "ui_refused", "url_refused", "perm_refused", "perm_confirm",
}
_local = threading.local()


def reset_keys() -> None:
    _local.keys = []


def used_keys() -> list[str]:
    return list(getattr(_local, "keys", []))


def R(cfg, key: str, **kw) -> str:
    """Phrase prête à être prononcée (variante au hasard, variables remplies)."""
    if key not in CATALOG:
        log.warning("phrase inconnue : %s", key)
    if not hasattr(_local, "keys"):
        _local.keys = []
    _local.keys.append(key)
    name = (cfg["user_name"] or "").strip()
    kw.setdefault("appel", f", {name}" if name else "")
    text = _fmt(random.choice(variants(cfg, key)), **kw)
    text = text.replace(" ,", ",").replace(" .", ".")
    return text


def all_variants(cfg, key: str) -> list[str]:
    """Toutes les formulations possibles d'une phrase, prêtes à être prononcées (pour préchauffer la voix)."""
    name = (cfg["user_name"] or "").strip()
    kw = {"appel": f", {name}" if name else ""}
    return [_fmt(v, **kw).replace(" ,", ",") for v in variants(cfg, key)]


def join(*parts: str) -> str:
    """Assemble des morceaux de phrase en ignorant les vides."""
    return " ".join(p.strip() for p in parts if p and p.strip())


def editable() -> list[tuple[str, str, tuple]]:
    """(clé, libellé, variables) des phrases proposées dans la page Réponses."""
    return [(k, v[0], v[1]) for k, v in CATALOG.items() if v[0]]


def default_text(cfg, key: str) -> str:
    """Première variante du style actuel (sans personnalisation), pour l'aperçu."""
    styles = CATALOG[key][2]
    return (styles.get(cfg["reply_style"]) or styles["jarvis"])[0]


SAMPLE = {
    "p": 40, "title": "Life", "name": "Discord", "query": "Damso", "heure": "15 heures 30",
    "date": "dimanche 20 septembre 2026", "duree": "5 minutes", "label": "les pâtes", "ville": "Lille",
    "temp": "12", "desc": "pluie faible", "tmax": "14", "tmin": "8", "heard": "blabla", "pluie": 70,
    "err": "erreur", "playlist": "rap fr", "reste": "3 minutes", "n": 2,
}


def preview(cfg, key: str, text: str = "") -> str:
    """Phrase d'exemple (variables remplies avec des valeurs factices), avec ou sans texte perso."""
    name = (cfg["user_name"] or "").strip()
    kw = dict(SAMPLE)
    kw["appel"] = f", {name}" if name else ""
    text = (text or "").strip()
    if text:
        options = [v.strip() for v in text.split("|") if v.strip()]
        return _fmt(random.choice(options), **kw) if options else ""
    return R(cfg, key, **kw)
