"""Compréhension des commandes vocales françaises.

Module en Python pur (aucune dépendance) : texte -> Intent.
Le modèle Vosk français renvoie les nombres en toutes lettres
("quarante"), donc on gère aussi la conversion mots -> chiffres.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class Intent:
    name: str
    args: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """minuscules, sans accents, sans ponctuation ("l'app" -> "l app")."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("œ", "oe")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# Nombres français (0 - 100)
# --------------------------------------------------------------------------- #
_UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
}
_TENS = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40,
         "cinquante": 50, "soixante": 60}
_NUMWORDS = set(_UNITS) | set(_TENS) | {"cent", "cents"}


def _words_to_int(tokens: list[str]) -> int:
    toks = [t for t in tokens if t != "et"]
    parts: list = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "quatre" and i + 1 < len(toks) and toks[i + 1] in ("vingt", "vingts"):
            parts.append(80)
            i += 2
            continue
        if t in _UNITS:
            parts.append(_UNITS[t])
        elif t in _TENS:
            parts.append(_TENS[t])
        elif t in ("cent", "cents"):
            parts.append("C")
        i += 1
    total = 0
    for p in parts:
        total = (total or 1) * 100 if p == "C" else total + p
    return total


def extract_number(n: str) -> tuple[int | None, str]:
    """Premier nombre du texte normalisé -> (valeur, mot qui le précède)."""
    n = re.sub(r"\bpour ?cent\b", " ", n)
    tokens = n.split()
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        if tok in ("un", "une") and i + 1 < len(tokens) and tokens[i + 1] == "peu":
            continue  # "un peu" n'est pas le nombre 1
        if tok in ("un", "une") and prev not in ("a", "de", "d", "sur", "au", "en"):
            continue  # article (« un baisse le son » = bruit), pas le nombre 1
        if tok.isdigit():
            return int(tok), prev
        if tok in _NUMWORDS:
            run, j = [], i
            while j < len(tokens) and (
                tokens[j] in _NUMWORDS
                or (tokens[j] == "et" and j + 1 < len(tokens) and tokens[j + 1] in _NUMWORDS)
            ):
                run.append(tokens[j])
                j += 1
            return _words_to_int(run), prev
    return None, ""


# --------------------------------------------------------------------------- #
# Analyse des commandes
# --------------------------------------------------------------------------- #
_FILLERS = re.compile(
    r"\b(s il (te|vous) plait|stp|svp|peux tu|pouvez vous|pourrais tu|"
    r"est ce que tu peux|tu peux|je voudrais|j aimerais|je veux|merci|moi|"
    r"please|alors|bon|allez|hop|euh|heu|hum|ben|bah|ah|oh)\b"
)
_PLAY = r"(?:mets|met|mettre|joue|jouer|joues|ecoute|ecouter|lance|lancer|passe|passer|balance|balancer|demarre|demarrer|diffuse|diffuser)"
_SOFT_PLAY = {"lance", "lancer", "passe", "passer", "demarre", "demarrer"}  # ambigus avec "ouvrir une app"
_OPEN = r"(?:lance|lancer|ouvre|ouvrir|demarre|demarrer|execute|executer|start|open|allume|va sur)"
_MUSIC_WORDS = r"\b(playlist|liste de lecture|chanson|musique|morceau|titre|album|clip)\b"


def clean(text: str) -> str:
    """Phrase normalisée sans mots de remplissage (sert à comparer des phrases entre elles)."""
    return re.sub(r"\s+", " ", _FILLERS.sub(" ", normalize(text))).strip()


def parse_command(text: str) -> Intent:
    """Texte parlé -> Intent. Essaie d'abord tel quel, puis répare les erreurs de reconnaissance
    fréquentes (verbe mal entendu, mot parasite au début)."""
    raw = normalize(text)
    n = re.sub(r"\s+", " ", _FILLERS.sub(" ", raw)).strip()
    it = _parse(n, raw)
    if it.name != "unknown":
        return it
    toks = n.split()
    tries = []
    if toks:
        fixed = _fix_first_verb(toks)
        if fixed != toks:
            tries.append(fixed)
        for k in (1, 2):                      # mot parasite (court) devant la commande
            if len(toks) > k and all(len(t) <= 3 for t in toks[:k]):
                tries.append(toks[k:])
                fixed = _fix_first_verb(toks[k:])
                if fixed != toks[k:]:
                    tries.append(fixed)
    for cand in tries:
        alt = _parse(" ".join(cand), raw)
        if alt.name not in ("unknown", "empty"):
            return alt
    return it


def _parse(n: str, raw: str) -> Intent:
    if not raw:
        return Intent("empty")

    # -- quitter l'assistant -------------------------------------------------
    if re.search(r"\b(eteins|ferme|quitte|arrete|desactive) (toi|sentinel|l assistant)\b", n):
        return Intent("quit")

    # -- politesses (on regarde le texte AVANT retrait des mots de remplissage) --
    if re.fullmatch(r"(?:sentinel )?(?:merci|un grand merci|merci beaucoup)(?: sentinel)?", raw):
        return Intent("smalltalk", {"kind": "thanks"})
    if re.fullmatch(r"(?:sentinel )?(?:bonjour|salut|coucou|hello|hey|bonsoir|yo)(?: sentinel)?", raw):
        return Intent("smalltalk", {"kind": "hello"})
    if len(raw.split()) <= 5 and re.search(r"\bca va\b|\bcomment (?:vas tu|tu vas|ca va|allez vous)\b|\btu vas bien\b", raw):
        return Intent("smalltalk", {"kind": "howareyou"})
    if len(raw.split()) <= 5 and re.search(r"\bqui es tu\b|\btu es qui\b|\bcomment (?:tu t appelles|t appelles tu)\b", raw):
        return Intent("smalltalk", {"kind": "whoareyou"})
    if (re.fullmatch(r"(?:aide|aide moi|help|les commandes|tes commandes|liste des commandes)", n)
            or re.search(r"\bqu est ce que tu (?:sais|peux) faire\b|\bque sais tu faire\b|\bque peux tu faire\b", n)):
        return Intent("smalltalk", {"kind": "help"})

    if not n:
        return Intent("empty")

    # -- heure / date --------------------------------------------------------
    if re.search(r"\bquelle heure\b|\bl heure qu il est\b", n):
        return Intent("time")
    if re.search(r"\bquel jour\b|\bquelle date\b|\bla date\b", n):
        return Intent("date")

    # -- minuteurs -----------------------------------------------------------
    timer = _parse_timer(n)
    if timer:
        return timer

    # -- capture d'écran -----------------------------------------------------
    if re.search(r"\bcapture d? ?ecran\b|\bscreenshot\b|\bscreen ?shot\b|\b(?:fais|fait|prends|prend|realise) (?:un |une )?(?:screen|capture)\b", n):
        return Intent("screenshot")

    # -- veille / verrouillage -------------------------------------------------
    if re.search(r"\b(?:en veille|hiberne\w*|mise en veille)\b", n) or re.fullmatch(r"veille", n):
        return Intent("unknown", {"text": n}) if re.search(r"\btoi\b", n) else Intent("sleep")
    if re.search(r"\bverrouill\w*\b|\bbloque (?:l |la |mon |le )?(?:ordinateur|pc|session|ecran)\b|\block\b", n):
        return Intent("lock")

    # -- fenêtres --------------------------------------------------------------
    if (re.search(r"\b(?:change|changer|bascule|basculer|passe|passer)\b (?:de |a |sur |vers )?(?:la |l |cette |une |une autre )?"
                  r"(?:fenetre|application|appli)(?: suivante| precedente| d apres| d avant)?$", n)
            or re.search(r"\bfenetre (?:suivante|precedente)\b|\balt tab\b", n)):
        return Intent("window_switch")
    if re.search(r"\b(?:affiche|montre|va sur|retourne sur|reviens sur|revenir sur|minimise tout|reduis tout|reduire tout)\b.*\bbureau\b", n) or n == "bureau":
        return Intent("desktop")

    # -- météo ---------------------------------------------------------------
    weather = _parse_weather(n)
    if weather:
        return weather

    # -- luminosité de l'écran -------------------------------------------------
    if re.search(r"\bluminosite\b|\b(?:eclaircis|assombris)\b|\becran (?:plus|moins) (?:lumineux|sombre|clair)\b", n):
        num, prev = extract_number(n)
        up = re.search(r"\b(monte|monter|augmente|augmenter|hausse|remonte|remonter|eclaircis|plus fort|plus haut|plus lumineux|plus clair)\b", n)
        down = re.search(r"\b(baisse|baisser|diminue|diminuer|reduis|reduire|descend|descendre|assombris|moins|plus bas|plus sombre)\b", n)
        if num is None and re.search(r"\bquelle?\b|\bactuelle?\b|\bcombien\b", n):
            return Intent("brightness_get")
        if num is not None:
            if prev in ("de", "d") and (up or down):
                return Intent("brightness_rel", {"direction": 1 if (up and not down) else -1, "amount": num})
            return Intent("brightness_set", {"value": max(0, min(100, num))})
        if re.search(r"\b(maximum|max|a fond)\b", n):
            return Intent("brightness_set", {"value": 100})
        if re.search(r"\b(minimum|min)\b", n):
            return Intent("brightness_set", {"value": 0})
        if up or down:
            amount = 5 if re.search(r"\bun peu\b|\blegerement\b", n) else (25 if re.search(r"\bbeaucoup\b|\bnettement\b", n) else None)
            return Intent("brightness_rel", {"direction": 1 if (up and not down) else -1, "amount": amount})

    # -- Discord -------------------------------------------------------------
    discordish = re.search(
        r"\b(discord|micro|microphone|casque|sourdine|salon|vocal|vocale|channel|canal|"
        r"mute|mutes|muter|muet|demute|demuter|unmute|deafen)\b", n)
    volumeish = re.search(r"\b(volume|son)\b", n)
    explicit_dc = re.search(r"\b(micro|microphone|discord|casque)\b", n)
    if discordish and not (volumeish and not explicit_dc):
        if (re.search(r"\b(quitte|quitter|deconnecte|deconnecter|sors|sortir|raccroche|raccrocher|part|partir)\b", n)
                and re.search(r"\b(salon|vocal|vocale|channel|canal|discord|appel|conversation)\b", n)):
            return Intent("discord_leave")
        if re.search(r"\b(sourdine|casque|deafen|assourdi\w*)\b", n):
            off = re.search(r"\b(reactive|reactiver|remets|remettre|enleve|enlever|retire|retirer|"
                            r"desactive|desactiver|annule|annuler|sors|fin)\b", n)
            return Intent("discord_deafen", {"on": not off})
        if re.search(r"\b(bascule|inverse|switch|toggle)\b", n):
            return Intent("discord_toggle")
        if (re.search(r"\b(demute\w*|unmut\w*)\b|\bde mut\w*", n)
                or re.search(r"\b(reactive|reactiver|remets|remettre|remet|rallume|rallumer|allume|active|activer|ouvre|ouvrir)\b.*\b(micro|microphone)\b", n)):
            return Intent("discord_mute", {"mute": False})
        if (re.search(r"\b(mut\w*|muet|muette)\b", n)
                or re.search(r"\b(coupe|couper|desactive|desactiver|eteins|eteindre|ferme|fermer)\b.*\b(micro|microphone)\b", n)):
            return Intent("discord_mute", {"mute": True})

    # -- Contrôle média (touches multimédia) ---------------------------------
    if re.search(r"\b(mets? en pause|mettre en pause|pause|(arrete|stop|stoppe|coupe) la (musique|chanson|lecture))\b", n):
        return Intent("media", {"action": "playpause"})
    if re.search(r"\b(reprends|reprendre|relance la (musique|chanson|lecture)|remets la (musique|chanson|lecture)|continue la (musique|lecture))\b", n):
        return Intent("media", {"action": "playpause"})
    if re.search(r"\b(suivant|suivante|prochain|prochaine|next)\b|\b(passe|change|saute)( de| cette| ce| la)? (musique|chanson|titre|morceau|piste)\b", n):
        return Intent("media", {"action": "next"})
    if re.search(r"\b(precedent|precedente|previous|reviens en arriere|retour en arriere|morceau d avant)\b", n):
        return Intent("media", {"action": "prev"})

    # -- Volume Windows ------------------------------------------------------
    if re.search(r"\bvolume\b|\ble son\b|\bles sons\b|\bsonore\b", n):
        num, prev = extract_number(n)
        up = re.search(r"\b(monte|monter|augmente|augmenter|hausse|remonte|remonter|plus fort)\b", n)
        down = re.search(r"\b(baisse|baisser|diminue|diminuer|reduis|reduire|descend|descendre|moins fort|plus bas)\b", n)
        if num is None and re.search(r"\bquel\b|\bactuel\b|\bcombien\b", n):
            return Intent("volume_get")
        if num is not None:
            if prev in ("de", "d") and (up or down):
                return Intent("volume_rel", {"direction": 1 if (up and not down) else -1, "amount": num})
            return Intent("volume_set", {"value": max(0, min(100, num))})
        if re.search(r"\b(maximum|max|a fond)\b", n):
            return Intent("volume_set", {"value": 100})
        if re.search(r"\b(minimum|min)\b", n):
            return Intent("volume_set", {"value": 0})
        if up or down:
            amount = 5 if re.search(r"\bun peu\b|\blegerement\b", n) else (25 if re.search(r"\bbeaucoup\b|\bnettement\b", n) else None)
            return Intent("volume_rel", {"direction": 1 if (up and not down) else -1, "amount": amount})
        if re.search(r"\b(coupe|couper|mute|muet|desactive|desactiver|eteins|eteindre|silence)\b", n):
            return Intent("volume_mute", {"mute": True})
        if re.search(r"\b(reactive|reactiver|remets|remettre|remet|mets|met|retablis|retablir|rallume|rallumer)\b", n):
            return Intent("volume_mute", {"mute": False})

    # -- Fermer une fenêtre / un onglet / une application ------------------------
    closing = _parse_close(n)
    if closing:
        return closing

    # -- Dossiers et fichiers du PC ------------------------------------------------
    opening = _parse_open_path(n)
    if opening:
        return opening

    # -- Raccourcis usuels dans l'application active (onglets, copier/coller, défilement…) -------
    for pattern, keys in _KEY_RULES:
        if re.match(pattern, n):
            return Intent("press_keys", {"keys": keys})
    for pattern, direction in _SCROLL_RULES:
        if re.match(pattern, n):
            return Intent("scroll", {"direction": direction})

    # -- Recherche web -------------------------------------------------------
    m = re.search(r"\b(?:cherche|chercher|recherche|rechercher)\s+(.+)$", n) or re.match(r"^(?:google|googler)\s+(.+)$", n)
    if m:                                                    # (« ouvre Google Chrome » n'est PAS une recherche)
        q = m.group(1)
        engine = None
        em = re.search(r"\b(?:sur|dans|avec)\s+(google|bing|youtube|duckduckgo)\b", q)
        if em:
            engine = em.group(1)
        q = re.sub(r"\b(?:sur|dans|avec)\s+(?:google|bing|youtube|duckduckgo|internet|le web|le net)\b", " ", q)
        q = re.sub(r"^(?:des )?(?:infos|informations)?\s*(?:sur|a propos de)?\s+", "", q) if q.startswith(("des infos", "des informations")) else q
        q = re.sub(r"\s+", " ", q).strip()
        if q:
            return Intent("web", {"query": q, "engine": engine})

    # -- "joue à <jeu>" -> application (avant la musique) -------------------
    m = re.match(r"^(?:on )?(?:joue|jouer|je joue) a (.+)$", n)
    if m:
        return Intent("open_app", {"name": _clean_app(m.group(1))})

    # -- Musique -------------------------------------------------------------
    music = _parse_music(n)
    if music:
        return music

    # -- Lancer une application / un jeu ------------------------------------
    m = re.match(rf"^{_OPEN}\s+(.+)$", n)
    if m:
        return Intent("open_app", {"name": _clean_app(m.group(1))})

    return Intent("unknown", {"text": n})


def _clean_app(name: str) -> str:
    name = re.sub(r"^(?:(?:l|le|la|les|un|une|mon|ma|application|app|jeu|logiciel|programme|site)\s+)+", "", name)
    return name.strip()


def _parse_music(n: str) -> Intent | None:
    m = re.match(rf"^(?:on )?({_PLAY})\s+(.*)$", n)
    if not m:
        return None
    verb, rest = m.group(1), m.group(2)
    provider = None
    pm = re.search(r"\b(?:sur|avec|dans|via)\s+(spotify|you ?tube music|youtube|deezer)\s*$", rest)
    if pm:
        provider = "spotify" if "spotify" in pm.group(1) else ("ytmusic" if "music" in pm.group(1) else "youtube")
        rest = rest[:pm.start()].strip()
    has_music_word = re.search(_MUSIC_WORDS, n)
    if verb in _SOFT_PLAY and not has_music_word:
        return None  # "lance chrome" -> application

    # playlist ciblée ?
    playlist = None
    track = rest
    pm = re.search(r"\b(?:dans|depuis|de|sur|a partir de)\s+(?:la |ma |mon |cette |l )?(?:playlist|liste de lecture)\s+(.+)$", rest)
    if not pm:
        pm = re.search(r"\b(?:la |ma |mon |cette |l )?(?:playlist|liste de lecture)\s+(.+)$", rest)
    if pm:
        playlist = re.sub(r"^(?:de|du|d|des)\s+", "", pm.group(1).strip())
        track = re.sub(r"^(?:une|un|la|le|l|cette|ce|ma|mon)$", "", rest[:pm.start()].strip())

    # "mets du Damso" / "de la musique de ..." -> mode radio
    radio = bool(re.match(r"^(?:du|de la|des|de l|d)\s+", track))
    track = re.sub(r"^(?:du|de la|des|de l|d)\s+", "", track)
    track = re.sub(r"^(?:la |le |l |une |un |cette |ce )?(?:chanson|musique|morceau|titre|piste|album|clip|son)\s*(?:de |du |d |des )?", "", track)
    return Intent("music", {"query": track.strip(), "playlist": playlist, "radio": radio, "provider": provider})


# --------------------------------------------------------------------------- #
# Durées (minuteurs)
# --------------------------------------------------------------------------- #
def numbers_to_digits(n: str) -> str:
    """« deux minutes trente » -> « 2 minutes 30 » (suites de nombres écrits en lettres -> chiffres)."""
    toks, out, i = n.split(), [], 0
    while i < len(toks):
        if toks[i] in _NUMWORDS:
            j, run = i, []
            while j < len(toks) and (toks[j] in _NUMWORDS
                                     or (toks[j] == "et" and j + 1 < len(toks) and toks[j + 1] in _NUMWORDS)):
                run.append(toks[j])
                j += 1
            out.append(str(_words_to_int(run)))
            i = j
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


_TIMER_TOKENS = {"minuteur", "minuteurs", "minuterie", "chrono", "chronometre", "timer", "compte"}
_UNIT = {"h": 3600, "heure": 3600, "heures": 3600, "min": 60, "mins": 60, "mn": 60, "minute": 60,
         "minutes": 60, "s": 1, "sec": 1, "secs": 1, "seconde": 1, "secondes": 1}


def parse_duration(n: str) -> tuple[int | None, set[int], list[str]]:
    """Durée en secondes trouvée dans le texte + indices des mots utilisés + mots (avec chiffres).

    Comprend : « 5 minutes », « une heure trente », « 1h30 », « deux minutes trente »,
    « un quart d'heure », « trois quarts d'heure », « une demi-heure », « une heure et demie ».
    """
    d = numbers_to_digits(n)
    d = re.sub(r"(\d)([a-z])", r"\1 \2", d)
    d = re.sub(r"([a-z])(\d)", r"\1 \2", d)
    toks = d.split()
    total, used, last, found = 0, set(), None, False
    bare: list[tuple[int, int]] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if t.isdigit():
            val = int(t)
            if nxt in _UNIT:
                mult = _UNIT[nxt]
                total += val * mult
                used |= {i, i + 1}
                found = True
                last = "h" if mult == 3600 else "m" if mult == 60 else "s"
                i += 2
                if i + 1 < len(toks) and toks[i] == "et" and toks[i + 1] in ("demie", "demi", "quart"):
                    quart = toks[i + 1] == "quart"
                    total += (900 if quart else 1800) if last == "h" else ((15 if quart else 30) if last == "m" else 0)
                    used |= {i, i + 1}
                    i += 2
                    last = None
                continue
            if nxt in ("quart", "quarts") and toks[i + 2:i + 4] == ["d", "heure"]:
                total += val * 900
                used |= {i, i + 1, i + 2, i + 3}
                found, last = True, None
                i += 4
                continue
            if nxt in ("demi", "demie") and toks[i + 2:i + 3] == ["heure"]:
                total += val * 1800
                used |= {i, i + 1, i + 2}
                found, last = True, None
                i += 3
                continue
            if last in ("h", "m") and (i - 1) in used:      # « 2 heures 30 » / « 2 minutes 30 »
                total += val * (60 if last == "h" else 1)
                used.add(i)
                found = True
                last = "m" if last == "h" else "s"
                i += 1
                continue
            if nxt not in _TIMER_TOKENS:          # « un minuteur » : « un » est un article
                bare.append((i, val))
            i += 1
            continue
        if t == "quart" and toks[i + 1:i + 3] == ["d", "heure"]:
            total += 900
            used |= {i, i + 1, i + 2}
            found, last = True, None
            i += 3
            continue
        if t in ("demi", "demie") and toks[i + 1:i + 2] == ["heure"]:
            total += 1800
            used |= {i, i + 1}
            found, last = True, None
            i += 2
            continue
        i += 1
    if not found and bare:                 # « minuteur de 10 » -> 10 minutes
        idx, val = bare[-1]
        total, found = val * 60, True
        used.add(idx)
    return (total if found and total > 0 else None), used, toks


_TIMER_WORD = r"\b(?:minuteur|minuteurs|minuterie|chrono|chronometre|timer|compte a rebours)\b"
_TIMER_REMIND = r"\b(?:reveille|rappelle|previens|previent|alerte)(?: moi)?\b"


def _timer_label(toks: list[str], used: set[int]) -> str | None:
    rem = " ".join(t for i, t in enumerate(toks) if i not in used)
    rem = re.sub(rf"^.*?(?:{_TIMER_WORD[2:-2]}|{_TIMER_REMIND[2:-2]})", "", rem)
    edge = r"(?:dans|pendant|pour|de|d|que|qu|un|une|1|a)"
    rem = re.sub(rf"^(?:{edge}\s+)+", "", rem.strip())
    rem = re.sub(rf"(?:\s+{edge})+$", "", rem.strip())
    rem = re.sub(rf"^{edge}$", "", rem).strip()
    return rem if 2 <= len(rem) <= 40 else None


def _parse_timer(n: str) -> Intent | None:
    has_word = re.search(_TIMER_WORD, n)
    has_remind = re.search(_TIMER_REMIND, n)
    if not has_word and re.search(r"\bcombien de temps (?:il )?reste\b|\btemps restant\b|\bil reste combien\b", n):
        return Intent("timer_get")
    if not (has_word or has_remind):
        return None
    if has_word and re.search(r"\b(?:annule|annuler|supprime|supprimer|arrete|arreter|stoppe|stopper|efface|effacer|desactive|desactiver)\b", n):
        return Intent("timer_cancel")

    seconds, used, toks = parse_duration(n)

    # alarme à heure fixe : « réveille-moi à 7 heures 30 »
    d = " ".join(toks)
    am = re.search(r"\ba (\d{1,2}) (?:h|heures?)(?: (\d{1,2}))?\b", d)
    if am and not re.search(r"\bdans\b", d) and has_remind:
        import datetime as _dt
        now = _dt.datetime.now()
        target = now.replace(hour=int(am.group(1)) % 24, minute=int(am.group(2) or 0), second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        return Intent("timer_set", {"seconds": int((target - now).total_seconds()), "label": "réveil"})

    if has_word and seconds is None and re.search(r"\bcombien\b|\breste\b|\brestant\b|\bou en est\b|\bquel temps\b", n):
        return Intent("timer_get")
    if seconds is None:
        return Intent("timer_set", {"seconds": None, "label": None}) if has_word else None
    return Intent("timer_set", {"seconds": seconds, "label": _timer_label(toks, used)})


# --------------------------------------------------------------------------- #
# Météo
# --------------------------------------------------------------------------- #
def _parse_weather(n: str) -> Intent | None:
    if not (re.search(r"\bmeteo\b|\bquel temps (?:fait il|il fait)\b|\bil fait quel temps\b|\btemps qu il fait\b|\btemperature\b", n)
            or re.search(r"\bpleuvoir\b|\bneiger\b|\bil (?:va )?pleut\b|\bil fait (?:chaud|froid|beau|combien)\b|\bfait il (?:chaud|froid|beau)\b", n)
            or re.search(r"\bva t il (?:pleuvoir|neiger|faire)\b", n)):
        return None
    when = "tomorrow" if re.search(r"\bdemain\b", n) else "today"
    cleaned = re.sub(r"\b(?:demain|aujourd hui|ce soir|ce matin|maintenant|actuellement|dehors|en ce moment)\b", " ", n)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    city = None
    m = re.search(r"\b(?:a|de|pour|sur|dans|en|au)\s+(?:la |le |l |les )?([a-z][a-z ]{1,30})$", cleaned)
    if m:
        cand = m.group(1).strip()
        if cand not in ("meteo", "la meteo", "temperature") and not re.search(r"\b(?:meteo|temps|temperature|fait|pleuvoir)\b", cand):
            city = cand
    if city is None:
        m = re.search(r"\bmeteo (?:de |a |pour )?([a-z][a-z ]{1,30})$", cleaned)
        if (m and len(m.group(1).strip()) >= 3 and m.group(1).strip() not in ("de", "du", "pour", "la", "les")
                and not re.search(r"\b(?:temps|temperature|fait|pleuvoir)\b", m.group(1))):
            city = m.group(1).strip()
    return Intent("weather", {"when": when, "city": city})


# --------------------------------------------------------------------------- #
# Fermeture
# --------------------------------------------------------------------------- #
_CLOSE_VERB = r"(?:ferme|fermer|quitte|quitter|termine|terminer|arrete|arreter|stoppe|stopper|tue|tuer|kill)"
_NOT_APPS = {"son", "volume", "musique", "micro", "microphone", "ecran", "tout", "windows", "ordinateur", "pc",
             "sentinel", "toi", "salon", "vocal", "casque", "sourdine"}


def _parse_close(n: str) -> Intent | None:
    force = False
    m = re.match(r"^(?:force|forcer) (?:la fermeture )?(?:de |d )?(.+)$", n)
    if m:
        force, target = True, m.group(1)
    else:
        m = re.match(rf"^({_CLOSE_VERB})\s+(.+)$", n)
        if not m:
            return None
        force, target = m.group(1) in ("tue", "tuer", "kill"), m.group(2)
    if re.fullmatch(r"(?:la |le |un |cette |cet |l )?(?:fenetre|page|appli|application|app|programme|jeu|ca|cela|ce truc)"
                    r"(?: en cours| active| actuelle| ouverte)?", target):
        return Intent("window_close")
    if re.fullmatch(r"(?:l |cet |cette |mon |un )?onglet(?: actuel| en cours| ouvert)?", target):
        return Intent("tab_close")
    target = _clean_app(target)
    if not target or target in _NOT_APPS:
        return None
    return Intent("close_app", {"name": target, "force": force})


# --------------------------------------------------------------------------- #
# Réparation d'un verbe mal reconnu (« baise le son » -> « baisse le son »)
# --------------------------------------------------------------------------- #
_VERBS = ["mets", "lance", "ouvre", "ferme", "baisse", "monte", "augmente", "diminue", "coupe", "cherche",
          "recherche", "joue", "passe", "prends", "verrouille", "annule", "arrete", "active", "desactive",
          "reactive", "demute", "remets", "eteins", "quitte", "affiche", "montre", "regle", "change", "tue",
          "stoppe", "reveille", "rappelle", "previens", "supprime", "fais", "bascule", "demarre", "reduis"]
_KNOWN_FIRST = set(_VERBS) | {
    "pause", "suivant", "suivante", "precedent", "precedente", "prochain", "reprends", "quel", "quelle",
    "quels", "combien", "est", "il", "on", "le", "la", "les", "un", "une", "de", "du", "des", "je", "tu",
    "volume", "musique", "son", "micro", "plus", "moins", "meteo", "veille", "capture", "fenetre", "minuteur",
    "chrono", "timer", "aide", "bureau", "screenshot", "luminosite", "sourdine", "salon", "va", "vas", "met",
    "mettre", "lancer", "ouvrir", "fermer", "baisser", "monter", "couper", "jouer", "chercher", "passer",
}


def _fix_first_verb(toks: list[str]) -> list[str]:
    t = toks[0]
    if t in _KNOWN_FIRST or len(t) < 4:
        return toks
    best, score = None, 0.0
    for v in _VERBS:
        r = SequenceMatcher(None, t, v).ratio()
        if r > score:
            best, score = v, r
    return [best] + toks[1:] if best and score >= 0.78 else toks


# --------------------------------------------------------------------------- #
# Dossiers et fichiers
# --------------------------------------------------------------------------- #
_ART = r"(?:(?:le|la|l|mon|ma|mes|les|un|une)\s+)*"


def _parse_open_path(n: str) -> Intent | None:
    m = re.match(rf"^(?:ouvre|ouvrir|affiche|montre|va dans)\s+{_ART}(dossier|repertoire|fichier|document|pdf|photo|image|video)\s+(.+)$", n)
    if m:
        return Intent("open_path", {"kind": m.group(1), "query": m.group(2).strip()})
    m = re.match(rf"^(?:ouvre|ouvrir|affiche|montre|va dans|va sur)\s+{_ART}(telechargements?|downloads|documents|images|photos|videos|"
                 r"corbeille|ce pc|mon pc|mon ordinateur|disque [a-z]|lecteur [a-z])$", n)
    if m:
        return Intent("open_path", {"kind": None, "query": m.group(1)})
    return None


# --------------------------------------------------------------------------- #
# Raccourcis et défilement dans l'application active
# --------------------------------------------------------------------------- #
_KEY_RULES = [
    (r"^(?:ouvre |ouvrir |fais |cree )?(?:un )?(?:nouvel|nouveau) onglet$", "ctrl+t"),
    (r"^onglet suivant$", "ctrl+tab"),
    (r"^onglet precedent$", "ctrl+shift+tab"),
    (r"^rouvre (?:l onglet ferme|le dernier onglet)$", "ctrl+shift+t"),
    (r"^(?:actualise|recharge|rafraichis)(?: la page| cette page)?$", "f5"),
    (r"^(?:page precedente|retour en arriere|reviens en arriere|reviens a la page precedente)$", "alt+left"),
    (r"^copie(?: ca| le texte| la selection)?$", "ctrl+c"),
    (r"^colle(?: ca| le texte)?$", "ctrl+v"),
    (r"^selectionne tout$", "ctrl+a"),
    (r"^(?:annule la derniere action|defais)$", "ctrl+z"),
    (r"^refais$", "ctrl+y"),
    (r"^enregistre(?: le fichier| le document| ca)?$", "ctrl+s"),
    (r"^(?:plein ecran|mets en plein ecran)$", "f11"),
    (r"^(?:appuie sur entree|valide)$", "enter"),
    (r"^(?:appuie sur echap|echappe)$", "esc"),
]
_SCROLL_RULES = [
    (r"^(?:descends|descend|scrolle vers le bas|fais defiler vers le bas|defile vers le bas)(?: la page)?$", "down"),
    (r"^(?:monte la page|remonte la page|remonte|scrolle vers le haut|fais defiler vers le haut)$", "up"),
    (r"^(?:va |aller )?tout en haut(?: de la page)?$", "top"),
    (r"^(?:va |aller )?tout en bas(?: de la page)?$", "bottom"),
]
