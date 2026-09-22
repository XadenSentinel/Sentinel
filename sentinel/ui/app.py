"""Fenêtre principale de Sentinel (CustomTkinter, thème HUD façon Jarvis).

Toute l'interface tourne dans le thread principal. Les threads de l'assistant
(écoute, voix, commandes) lui parlent uniquement via `ui_queue`.
"""
from __future__ import annotations

import datetime
import logging
import os
import queue
import threading
import time
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from .. import __version__
from ..actions.timers import format_clock, format_duration
from ..actions.weather import symbol
from ..config import bundle_dir, export_profile, import_profile
from ..asr import WHISPER_MODELS
from ..nlu import normalize
from ..replies import STYLES, default_text, editable, fr_date, preview
from ..system import cpu_percent, ram_percent, restart_app, set_autostart
from ..updater import UpdateError
from ..tts import EDGE_VOICES
from ..voice import download_model, list_mics, list_voices
from .command_docs import COMMAND_DOCS
from .hud import Hud
from .theme import (ACCENTS, BG, BORDER, DANGER, DIM, FONT_HEAD, FONT_MONO, FONT_UI, OK, PANEL, PANEL2, TEXT, THEMES, is_hex)
from .tray import create_tray
from .widgets import KeyValueEditor

log = logging.getLogger("sentinel.ui")

PAGES = [("home", "◉", "ACCUEIL"), ("music", "♫", "MUSIQUE"), ("apps", "▣", "APPLIS & PC"), ("discord", "◈", "DISCORD"),
         ("commands", "☰", "COMMANDES"), ("brain", "✦", "CERVEAU IA"), ("replies", "✎", "RÉPONSES"),
         ("settings", "⚙", "PARAMÈTRES"), ("log", "≡", "JOURNAL")]

PROVIDERS = {
    "youtube": "YouTube — lecture instantanée",
    "ytmusic": "YouTube Music",
    "spotify": "Spotify — lecture directe (compte Premium)",
}
TTS_ENGINES = {"auto": "Automatique — voix neuronale, sinon Windows", "edge": "Voix neuronale Microsoft (en ligne)",
               "sapi": "Voix Windows (hors-ligne)"}
ASR_MODES = {False: "Vosk seul — rapide", True: "Vosk + Whisper — plus précis (recommandé)"}
BRAIN_MODES = {"auto": "Automatique — règles d'abord, l'IA si je ne comprends pas",
               "always": "Toujours l'IA (plus intelligent, un peu plus lent)"}
BRAIN_BACKENDS = {"ollama": "Ollama (recommandé, gratuit)", "openai": "Serveur compatible OpenAI (LM Studio…)",
                  "anthropic": "Claude — API Anthropic (le plus intelligent, payant à l'usage)"}
HUD_STYLES = {"stars": "Dégradé + étoiles", "gradient": "Dégradé", "solid": "Fond uni + grille", "minimal": "Minimal"}
ENGINES = {"google": "Google", "duckduckgo": "DuckDuckGo", "bing": "Bing"}

STATE_TEXT = {
    "loading": "INITIALISATION…", "idle": "EN VEILLE", "listening": "JE VOUS ÉCOUTE",
    "thinking": "TRAITEMENT…", "speaking": "RÉPONSE", "off": "ÉCOUTE COUPÉE",
    "nomodel": "MODÈLE VOCAL MANQUANT", "error": "ERREUR MICRO",
}


class SentinelApp(ctk.CTk):
    def __init__(self, cfg, assistant, ui_queue: "queue.Queue", start_hidden: bool = False) -> None:
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("dark")
        self.cfg, self.assistant, self.ui_queue = cfg, assistant, ui_queue
        self.accent = self._accent_color(cfg)
        self._tele_at = 0.0
        self._last_inter: dict | None = None
        self.web = None                 # contrôleur de l'interface web (None = ancienne interface seule)
        self.state_key = "loading"      # (pas « state » : nom réservé par Tk)
        self.current_page = "home"
        self._acc: list[tuple] = []     # widgets recolorés quand l'accent change
        self._closing = False
        self._brain = {"ok": False, "message": "Vérification…", "models": [], "model": ""}
        self._log_buffer: list[tuple[str, str, str]] = []          # (heure, genre, texte) : gardé même page Journal non construite
        self._last_asr: tuple[str, str] | None = None               # rejoué quand la page Paramètres se construit
        self._last_update: tuple[str, object] | None = None         # rejoué quand la page Paramètres se construit

        self.title(self._brand().upper())
        self._set_window_icon()
        self.geometry("1080x720")
        self.minsize(960, 660)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=18, pady=14)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # Chaque page ne construit ses widgets QUE la première fois qu'on l'ouvre (voir show_page). Avec
        # l'interface web active, cette fenêtre reste cachée et sert de secours : ça évite de fabriquer
        # huit pages entières de widgets pour rien, ce qui allège nettement la mémoire au démarrage.
        self._page_builders: dict[str, Callable] = {
            "home": self._build_home, "music": self._build_music, "apps": self._build_apps,
            "discord": self._build_discord, "commands": self._build_commands, "brain": self._build_brain,
            "replies": self._build_replies, "settings": self._build_settings, "log": self._build_log,
        }
        self.pages: dict[str, ctk.CTkBaseClass] = {}
        self.show_page("home")

        self.tray = create_tray(ui_queue, self.accent)
        self.after(60, self._poll_queue)
        if not cfg["first_run_done"]:
            self.after(1200, self._first_run)
        self.after(33, self._animate)
        self.after(200, self._tick)
        if start_hidden:
            self.withdraw() if self.tray else self.iconify()

    def _first_run(self) -> None:
        """Petit assistant de bienvenue (utile quand tu donnes Sentinel à un ami)."""
        if self._closing or self.web:
            return                                     # l'interface web a son propre assistant de bienvenue
        c = self.cfg
        win = ctk.CTkToplevel(self)
        win.title("Bienvenue")
        win.geometry("560x520")
        win.configure(fg_color=BG)
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="BIENVENUE", font=(FONT_HEAD, 22, "bold"), text_color=self.accent).pack(anchor="w", padx=22, pady=(18, 0))
        ctk.CTkLabel(win, text="Quelques questions pour personnaliser ton assistant (tout se change plus tard dans les Paramètres).",
                     wraplength=510, justify="left", anchor="w", text_color=DIM, font=(FONT_UI, 12)).pack(fill="x", padx=22, pady=(2, 10))
        v_name = ctk.StringVar(value=c["user_name"])
        v_wake = ctk.StringVar(value=c["wake_word"])
        v_city = ctk.StringVar(value=c["weather_city"])
        voices = {"Voix d'homme (Henri)": "fr-FR-HenriNeural", "Voix de femme (Denise)": "fr-FR-DeniseNeural"}
        v_voice = ctk.StringVar(value=next((k for k, v in voices.items() if v == c["tts_edge_voice"]), list(voices)[0]))
        v_style = ctk.StringVar(value=STYLES.get(c["reply_style"], STYLES["jarvis"]))
        for label, widget in (
            ("Comment dois-je t'appeler ?", ctk.CTkEntry(win, textvariable=v_name, placeholder_text="ton prénom")),
            ("Mot pour m'appeler (mot déclencheur)", ctk.CTkEntry(win, textvariable=v_wake, placeholder_text="ex. sentinel, jarvis, friday…")),
            ("Ta ville (pour la météo)", ctk.CTkEntry(win, textvariable=v_city, placeholder_text="ex. Lille")),
            ("Ma voix", ctk.CTkOptionMenu(win, values=list(voices), variable=v_voice, fg_color=PANEL2)),
            ("Ma façon de parler", ctk.CTkOptionMenu(win, values=list(STYLES.values()), variable=v_style, fg_color=PANEL2)),
        ):
            ctk.CTkLabel(win, text=label, anchor="w", text_color=TEXT, font=(FONT_UI, 13, "bold")).pack(fill="x", padx=22, pady=(6, 0))
            widget.pack(fill="x", padx=22, pady=(2, 0))

        def finish(save: bool) -> None:
            if save:
                c["user_name"] = v_name.get().strip()
                c["wake_word"] = (v_wake.get().strip().lower() or "sentinel")
                c["weather_city"] = v_city.get().strip()
                c["tts_edge_voice"] = voices[v_voice.get()]
                c["tts_gender"] = "male" if "Henri" in v_voice.get() else "female"
                c["reply_style"] = next((k for k, v in STYLES.items() if v == v_style.get()), "jarvis")
                self.assistant.refresh_weather()
                self.hud.set_text("hint", self._hint())
                self.stats["Voix"].configure(text=self._voice_name())
                self.hud.set_text("badge", self._badge())
            c["first_run_done"] = True
            c.save()
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(18, 0))
        self._btn(row, "Terminer", lambda: finish(True), width=150).pack(side="left")
        self._btn(row, "Plus tard", lambda: finish(False), width=120).pack(side="left", padx=8)

    def _set_window_icon(self) -> None:
        ico = bundle_dir() / "assets" / "sentinel.ico"
        if not ico.exists():
            return
        try:   # CustomTkinter réapplique son icône par défaut après ~200 ms : on passe après
            self.after(300, lambda: self.iconbitmap(str(ico)))
        except Exception:
            log.debug("icône de fenêtre non appliquée", exc_info=True)

    # ================================================================ helpers UI
    def _acc_reg(self, widget, *options: str):
        self._acc.append((widget, options))
        self._paint(widget, options)
        return widget

    def _paint(self, widget, options) -> None:
        try:
            widget.configure(**{o: self.accent for o in options})
        except Exception:
            pass

    def _btn(self, parent, text, command, width=150):
        b = ctk.CTkButton(parent, text=text, command=command, width=width, height=34,
                          fg_color="transparent", border_width=1, hover_color=PANEL2,
                          corner_radius=6, font=(FONT_UI, 13, "bold"))
        return self._acc_reg(b, "border_color", "text_color")

    @staticmethod
    def _accent_color(cfg) -> str:
        return cfg["custom_accent"] if is_hex(cfg["custom_accent"]) else ACCENTS.get(cfg["accent"], ACCENTS["Cyan"])

    def _brand(self) -> str:
        return (self.cfg["assistant_name"] or self.cfg["wake_word"] or "Sentinel").strip()

    def _title(self, parent, text, size=14):
        return self._acc_reg(ctk.CTkLabel(parent, text=text, font=(FONT_HEAD, size, "bold")), "text_color")

    def _page_title(self, parent, text):
        self._title(parent, text, 22).pack(anchor="w", pady=(0, 2))
        bar = ctk.CTkFrame(parent, height=2, width=64, fg_color=self.accent, corner_radius=1)
        self._acc_reg(bar, "fg_color")
        bar.pack(anchor="w", pady=(0, 12))

    def _card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=(0, 12))
        return card

    def _row(self, parent, label):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(row, text=label, anchor="w", text_color=TEXT, font=(FONT_UI, 13)).pack(side="left")
        return row

    def _save_dict(self) -> None:
        self.cfg.save()

    # ================================================================== sidebar
    def _logo_image(self):
        try:
            from PIL import Image
            ico = bundle_dir() / "assets" / "sentinel.ico"
            img = Image.open(ico).convert("RGBA").resize((40, 40))
            return ctk.CTkImage(light_image=img, dark_image=img, size=(40, 40))
        except Exception:
            log.debug("logo non chargé", exc_info=True)
            return None

    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, width=230, fg_color=PANEL, corner_radius=0, border_width=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.pack_propagate(False)                                  # largeur fixe, quel que soit le contenu
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(22, 0))
        logo = self._logo_image()
        if logo:
            ctk.CTkLabel(head, image=logo, text="").pack(side="left", padx=(0, 10))
        box = ctk.CTkFrame(head, fg_color="transparent")
        box.pack(side="left")
        self._title(box, self._brand().upper(), 22).pack(anchor="w")
        ctk.CTkLabel(box, text="ASSISTANT VOCAL", font=(FONT_MONO, 9), text_color=DIM).pack(anchor="w")
        line = ctk.CTkFrame(sb, height=1, fg_color=self.accent)
        self._acc_reg(line, "fg_color")
        line.pack(fill="x", padx=20, pady=16)

        self.nav: dict[str, ctk.CTkButton] = {}
        self.nav_bar: dict[str, ctk.CTkFrame] = {}
        for key, icon, label in PAGES:
            row = ctk.CTkFrame(sb, fg_color="transparent", height=42)
            row.pack(fill="x", padx=(0, 10), pady=1)
            bar = ctk.CTkFrame(row, width=3, height=26, fg_color="transparent", corner_radius=2)
            bar.pack(side="left", fill="y", pady=7)
            b = ctk.CTkButton(row, text=f" {icon}   {label}", anchor="w", height=40, corner_radius=8,
                              fg_color="transparent", hover_color=PANEL2, text_color=TEXT,
                              font=(FONT_UI, 13, "bold"), command=lambda k=key: self.show_page(k))
            b.pack(side="left", fill="x", expand=True, padx=(8, 0))
            self.nav[key], self.nav_bar[key] = b, bar
        self.lbl_version = ctk.CTkLabel(sb, text=f"v{__version__}", font=(FONT_MONO, 10), text_color=DIM, cursor="hand2")
        self.lbl_version.pack(side="bottom", pady=14)
        self.lbl_version.bind("<Button-1>", lambda _e: self.show_page("settings"))

    def _paint_nav(self) -> None:
        for key, b in self.nav.items():
            active = key == self.current_page
            b.configure(fg_color=PANEL2 if active else "transparent", text_color=self.accent if active else TEXT)
            self.nav_bar[key].configure(fg_color=self.accent if active else "transparent")

    def show_page(self, key: str) -> None:
        if key not in self._page_builders:
            return
        if key not in self.pages:
            holder = ctk.CTkFrame(self.content, fg_color="transparent")
            holder.grid(row=0, column=0, sticky="nsew")
            self._page_builders[key](holder).pack(fill="both", expand=True)
            self.pages[key] = holder
        self.current_page = key
        self.pages[key].tkraise()
        self._paint_nav()

    # ===================================================================== ACCUEIL
    def _voice_name(self) -> str:
        if self.cfg["tts_engine"] == "sapi":
            return (self.cfg["tts_voice"] or "Windows").split(" - ")[0].replace("Microsoft ", "")
        return EDGE_VOICES.get(self.cfg["tts_edge_voice"], self.cfg["tts_edge_voice"]).split(" — ")[0]

    def _badge(self) -> str:
        if not self.cfg["brain_enabled"]:
            ia = "IA DÉSACTIVÉE"
        else:
            ia = "IA EN LIGNE" if self._brain.get("ok") else "IA HORS LIGNE"
        return f"●  {ia}   ·   VOIX {self._voice_name().upper()}"

    def _build_home(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        self.hud = Hud(page, self.accent, self.cfg["hud_bg"], self.cfg["hud_fx"])
        self.hud.grid(row=0, column=0, sticky="nsew")
        self.hud.set_text("state", STATE_TEXT["loading"])
        self.hud.set_text("hint", self._hint())
        self.hud.set_text("badge", self._badge())

        right = ctk.CTkScrollableFrame(page, fg_color=PANEL, corner_radius=14, width=262, border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        self._title(right, "MÉTÉO").pack(anchor="w", padx=12, pady=(10, 4))
        self.lbl_wx_main = ctk.CTkLabel(right, text="—", text_color=TEXT, font=(FONT_UI, 22, "bold"), anchor="w")
        self.lbl_wx_main.pack(anchor="w", padx=12)
        self.lbl_wx_sub = ctk.CTkLabel(right, text="Chargement…", text_color=DIM, font=(FONT_UI, 12),
                                       anchor="w", justify="left", wraplength=230)
        self.lbl_wx_sub.pack(anchor="w", padx=12)
        ctk.CTkFrame(right, height=1, fg_color=BORDER).pack(fill="x", padx=12, pady=10)

        self._title(right, "MINUTEURS").pack(anchor="w", padx=12, pady=(0, 4))
        self.lbl_timers = ctk.CTkLabel(right, text="Aucun en cours", text_color=DIM, font=(FONT_MONO, 13),
                                       anchor="w", justify="left")
        self.lbl_timers.pack(anchor="w", padx=12)
        ctk.CTkFrame(right, height=1, fg_color=BORDER).pack(fill="x", padx=12, pady=10)

        self._title(right, "SYSTÈME").pack(anchor="w", padx=12, pady=(0, 6))
        self.stats: dict[str, ctk.CTkLabel] = {}
        for name, value in (("Micro", "…"), ("Modèle vocal", "…"), ("Whisper", "désactivé"), ("Voix", self._voice_name()),
                            ("Cerveau IA", "vérification…"), ("Applications", "indexation…"), ("Fichiers", "…")):
            row = ctk.CTkFrame(right, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=1)
            ctk.CTkLabel(row, text=name, text_color=DIM, font=(FONT_UI, 12), width=92, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(row, text=value, text_color=TEXT, font=(FONT_UI, 12), anchor="w", wraplength=140, justify="left")
            lbl.pack(side="left", fill="x", expand=True)
            self.stats[name] = lbl

        ctk.CTkFrame(right, height=1, fg_color=BORDER).pack(fill="x", padx=12, pady=10)
        self._title(right, "APPRENTISSAGE").pack(anchor="w", padx=12, pady=(0, 4))
        self.lbl_last = ctk.CTkLabel(right, text="Dis une commande : tu pourras me corriger ici.", text_color=DIM, font=(FONT_UI, 12),
                                     anchor="w", justify="left", wraplength=232)
        self.lbl_last.pack(anchor="w", padx=12)
        row = ctk.CTkFrame(right, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkButton(row, text="✓ Bien compris", width=108, height=30, corner_radius=6, fg_color=PANEL2, hover_color=BORDER,
                      font=(FONT_UI, 12, "bold"), command=self._learn_ok).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="✗ Mal compris", width=108, height=30, corner_radius=6, fg_color=PANEL2, hover_color=DANGER,
                      font=(FONT_UI, 12, "bold"), command=self._teach_dialog).pack(side="left")
        ctk.CTkFrame(right, height=1, fg_color=BORDER).pack(fill="x", padx=12, pady=10)
        self.sw_listen = ctk.CTkSwitch(right, text="Écoute active", font=(FONT_UI, 13), command=self._toggle_listen)
        self.sw_listen.select()
        self._acc_reg(self.sw_listen, "progress_color")
        self.sw_listen.pack(anchor="w", padx=12, pady=4)
        self._btn(right, "Parler maintenant", self.assistant.listener.trigger, width=226).pack(padx=12, pady=(10, 4))
        self._btn(right, "Test de la voix", lambda: self.assistant.speaker.say(
            "Systèmes opérationnels. Sentinel est à votre écoute."), width=226).pack(padx=12, pady=4)

        self.card_model = ctk.CTkFrame(right, fg_color=PANEL2, corner_radius=10)   # affiché si modèle absent
        ctk.CTkLabel(self.card_model, text="Le modèle de reconnaissance vocale\nfrançais (41 Mo) est requis.",
                     font=(FONT_UI, 12), text_color=TEXT, justify="left").pack(padx=12, pady=(10, 6), anchor="w")
        self.btn_dl = self._btn(self.card_model, "Télécharger", self._start_download, width=190)
        self.btn_dl.pack(padx=12, pady=4)
        self.bar_dl = ctk.CTkProgressBar(self.card_model, width=190)
        self._acc_reg(self.bar_dl, "progress_color")
        self.bar_dl.set(0)
        self.bar_dl.pack(padx=12, pady=(4, 12))
        return page

    def _hint(self) -> str:
        return f"Dites « {self.cfg['wake_word'].upper()} » puis votre commande"

    def _toggle_listen(self) -> None:
        self.assistant.set_listening(bool(self.sw_listen.get()))

    def _start_download(self) -> None:
        self.btn_dl.configure(state="disabled", text="Téléchargement…")

        def work():
            try:
                download_model(lambda f: self.ui_queue.put(("model_progress", f)))
                self.ui_queue.put(("model_done",))
            except Exception as exc:
                log.exception("téléchargement du modèle échoué")
                self.ui_queue.put(("model_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # ===================================================================== MUSIQUE
    def _build_music(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._page_title(page, "MUSIQUE")
        card = self._card(page)
        row = self._row(card, "Source de lecture")
        self.opt_provider = ctk.CTkOptionMenu(row, values=list(PROVIDERS.values()), width=330,
                                              fg_color=PANEL2, command=self._on_provider)
        self.opt_provider.set(PROVIDERS.get(self.cfg["music_provider"], PROVIDERS["youtube"]))
        self.opt_provider.pack(side="right")
        row = self._row(card, "Mode radio pour « mets du … » (enchaîne les titres)")
        self.sw_radio = ctk.CTkSwitch(row, text="", command=self._on_radio)
        self._acc_reg(self.sw_radio, "progress_color")
        (self.sw_radio.select if self.cfg["music_radio"] else self.sw_radio.deselect)()
        self.sw_radio.pack(side="right")
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=700, text_color=DIM, font=(FONT_UI, 12), text=(
            "YouTube : aucune clé d'API, Sentinel trouve la vidéo et l'ouvre dans ton navigateur.\n"
            "Spotify : lecture directe du titre demandé (voir la carte ci-dessous). Tu peux aussi choisir à la voix : "
            "« mets Life de Damso sur Spotify » · « joue Djadja sur YouTube ».\n"
            "Pour une playlist perso, colle son lien plus bas (nom = ce que tu dis à voix haute)."
        )).pack(fill="x", padx=14, pady=(4, 14))

        card = self._card(page)
        self._title(card, "SPOTIFY — LECTURE DIRECTE").pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=700, text_color=DIM, font=(FONT_UI, 12), text=(
            "Pour que « mets Life de Damso » lance vraiment le titre dans Spotify (comme Siri) :\n"
            "1. Va sur developer.spotify.com/dashboard → « Create app » (nom libre).\n"
            "2. Redirect URI : http://127.0.0.1:8888/callback   ·   coche « Web API » puis enregistre.\n"
            "3. Copie le Client ID de l'appli, colle-le ci-dessous puis clique sur « Connecter Spotify ».\n"
            "Règle de Spotify : la commande à distance demande un compte PREMIUM. Sans Premium (ou sans connexion), "
            "Sentinel joue le titre sur YouTube à la place — ça marche quand même.")).pack(fill="x", padx=14, pady=(0, 6))
        self.v_spid = ctk.StringVar(value=self.cfg["spotify_client_id"])
        row = self._row(card, "Client ID Spotify")
        ctk.CTkEntry(row, textvariable=self.v_spid, width=340, placeholder_text="ex. 3f9a…").pack(side="right")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 12))
        self._btn(row, "Connecter Spotify", self._spotify_connect, width=180).pack(side="left")
        self._btn(row, "Déconnecter", self._spotify_disconnect, width=130).pack(side="left", padx=8)
        self.lbl_spotify = ctk.CTkLabel(row, text="", font=(FONT_UI, 12), anchor="w")
        self.lbl_spotify.pack(side="left", padx=8)
        self._show_spotify("")

        KeyValueEditor(page, "MES PLAYLISTS", "Nom (ex. rap fr)", "Lien YouTube / YouTube Music / Spotify",
                       self.cfg["playlists"], self._save_dict).pack(fill="x")
        return page

    def _spotify_connect(self) -> None:
        self.cfg["spotify_client_id"] = self.v_spid.get().strip()
        self.cfg.save()
        if not self.cfg["spotify_client_id"]:
            self._show_spotify("Colle d'abord ton Client ID.")
            return
        self.lbl_spotify.configure(text="Autorise Sentinel dans ton navigateur…", text_color=DIM)
        spotify = self.assistant.music.spotify
        threading.Thread(target=lambda: self.ui_queue.put(("spotify_status", spotify.connect_blocking())),
                         daemon=True, name="sentinel-spotify-auth").start()

    def _spotify_disconnect(self) -> None:
        self.assistant.music.spotify.disconnect()
        self._show_spotify("Déconnecté.")

    def _show_spotify(self, message: str) -> None:
        connected = self.assistant.music.spotify.connected()
        text = message or ("Connecté ✓" if connected else "Non connecté")
        self.lbl_spotify.configure(text=text, text_color=OK if connected and "✓" in text else DIM)
        if message:
            self._append_log("info", f"Spotify : {message}")

    def _on_provider(self, label: str) -> None:
        self.cfg["music_provider"] = next(k for k, v in PROVIDERS.items() if v == label)
        self.cfg.save()

    def _on_radio(self) -> None:
        self.cfg["music_radio"] = bool(self.sw_radio.get())
        self.cfg.save()

    # ================================================================ APPLICATIONS
    def _build_apps(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._page_title(page, "APPLIS & PC")
        card = self._card(page)
        self._title(card, "ACCÈS À TON ORDINATEUR").pack(anchor="w", padx=14, pady=(12, 2))
        self.lbl_scan = ctk.CTkLabel(card, justify="left", anchor="w", wraplength=700, text_color=DIM, font=(FONT_UI, 12),
                                     text="Analyse en cours…")
        self.lbl_scan.pack(fill="x", padx=14)
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=700, text_color=DIM, font=(FONT_UI, 12), text=(
            "Sentinel connaît le menu Démarrer, Steam, Epic, le Bureau et — en plus — tous les programmes (.exe) trouvés "
            "sur tes disques, ainsi que tes dossiers et fichiers personnels.\n"
            "« lance Fortnite » · « ouvre HandBrake » · « ouvre mes téléchargements » · « ouvre le fichier CV ».\n\n"
            "Sécurité : Sentinel ouvre les choses comme un double-clic. Il ne désactive RIEN dans Windows : Defender, "
            "SmartScreen et la fenêtre de contrôle de compte (UAC) restent actifs. Il ne supprime ni ne déplace jamais "
            "de fichier et refuse d'ouvrir des scripts (.bat, .ps1, .vbs…).")).pack(fill="x", padx=14, pady=(6, 8))
        self.v_fulldisk = ctk.BooleanVar(value=self.cfg["scan_full_disk"])
        self._switch(card, "Analyser tous les disques (sinon : seulement les dossiers usuels)", self.v_fulldisk)
        self.v_extra = ctk.StringVar(value="; ".join(self.cfg["scan_extra_paths"]))
        row = self._row(card, "Dossiers en plus (séparés par ;)")
        ctk.CTkEntry(row, textvariable=self.v_extra, width=340, placeholder_text="ex. D:\\Jeux; E:\\Logiciels").pack(side="right")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(6, 12))
        self._btn(row, "Enregistrer et réanalyser", self._save_scan, width=220).pack(side="left")
        ctk.CTkLabel(row, text="(1re analyse : quelques minutes, en tâche de fond ; ensuite mise en cache 12 h)",
                     text_color=DIM, font=(FONT_UI, 11)).pack(side="left", padx=10)
        KeyValueEditor(page, "MES ALIAS (prioritaires)", "Nom prononcé (ex. fortnite)",
                       "Chemin .exe / lien steam:// / URL / commande",
                       self.cfg["app_aliases"], self._save_dict, browse=True).pack(fill="x")
        return page

    def _save_scan(self) -> None:
        self.cfg["scan_full_disk"] = bool(self.v_fulldisk.get())
        self.cfg["scan_extra_paths"] = [p.strip() for p in self.v_extra.get().split(";") if p.strip()]
        self.cfg.save()
        self.lbl_scan.configure(text="Analyse en cours…")
        self.assistant.apps.refresh_async(True)
        self.assistant.files.refresh_async(0.5)

    # ===================================================================== DISCORD
    def _build_discord(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self._page_title(page, "DISCORD")
        card = self._card(page)
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=700, text_color=DIM, font=(FONT_UI, 12), text=(
            "Sentinel appuie sur des raccourcis clavier GLOBAUX que tu déclares dans Discord :\n"
            "Discord → Paramètres utilisateur → Raccourcis clavier → Ajouter → choisis l'action, "
            "clique sur « Enregistrer le raccourci » et tape la même combinaison que ci-dessous.\n"
            "Actions à lier : « Activer/désactiver le micro » (Toggle Mute), « Activer/désactiver le casque » "
            "(Toggle Deafen) et, si ta version de Discord la propose, une action pour quitter le salon vocal.\n"
            "Commandes : « coupe mon micro » · « démute » · « mets-moi en sourdine » · « quitte le salon vocal »."
        )).pack(fill="x", padx=14, pady=(12, 8))
        self.dc_vars: dict[str, ctk.StringVar] = {}
        for action, label in (("toggle_mute", "Micro (activer / couper)"),
                              ("toggle_deafen", "Sourdine du casque"),
                              ("leave_voice", "Quitter le salon vocal")):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)
            ctk.CTkLabel(row, text=label, width=210, anchor="w", text_color=TEXT).pack(side="left")
            var = ctk.StringVar(value=self.cfg["discord_keys"].get(action, ""))
            ctk.CTkEntry(row, textvariable=var, width=210).pack(side="left", padx=6)
            self._btn(row, "Tester", lambda a=action: self._test_discord(a), width=90).pack(side="left", padx=6)
            self.dc_vars[action] = var
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 14))
        self._btn(row, "Enregistrer", self._save_discord, width=140).pack(side="left")
        self._btn(row, "Resynchroniser l'état du micro", self.assistant.discord.reset_state, width=250).pack(side="left", padx=10)
        return page

    def _save_discord(self) -> None:
        self.cfg["discord_keys"] = {a: v.get().strip().lower() for a, v in self.dc_vars.items()}
        self.cfg.save()

    def _test_discord(self, action: str) -> None:
        self._save_discord()
        threading.Thread(target=self.assistant.discord.test, args=(action,), daemon=True).start()

    # ==================================================================== COMMANDES
    def _build_commands(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self._page_title(page, "COMMANDES")

        # -- barre fixe : tester une phrase + rechercher
        card = self._card(page)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 4))
        self.e_test = ctk.CTkEntry(row, placeholder_text="Tape une phrase pour voir comment Sentinel la comprend…", height=34)
        self.e_test.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.e_test.bind("<Return>", lambda _e: self._test_analyze())
        self._btn(row, "Analyser", self._test_analyze, width=100).pack(side="left", padx=3)
        self._btn(row, "Exécuter", self._test_run, width=100).pack(side="left", padx=3)
        self.lbl_test = ctk.CTkLabel(card, text="Dis « " + self.cfg["wake_word"].capitalize() + " » puis une de ces phrases — "
                                     "les formulations proches marchent aussi, et l'IA comprend les phrases libres.",
                                     justify="left", anchor="w", wraplength=760, text_color=DIM, font=(FONT_MONO, 12))
        self.lbl_test.pack(fill="x", padx=14, pady=(0, 6))
        self.v_search = ctk.StringVar()
        self.v_search.trace_add("write", lambda *_: self._debounce_docs())
        ctk.CTkEntry(card, textvariable=self.v_search, height=32, placeholder_text="🔍  Rechercher une commande (ex. minuteur, volume, fichier, spotify…)"
                     ).pack(fill="x", padx=14, pady=(0, 12))

        # -- liste défilante
        self.docs_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.docs_scroll.pack(fill="both", expand=True)
        self._docs_job = None
        self.docs_holder = None
        self._render_docs()
        card = self._card(self.docs_scroll)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 2))
        self._title(head, "✦  CE QUE SENTINEL A APPRIS DE TOI").pack(side="left")
        self._btn(head, "Tout oublier", self._forget_learned, width=120).pack(side="right")
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 11), text=(
            "Chaque fois que tu cliques sur « ✗ Mal compris » (accueil) et que tu dis ce que tu voulais, Sentinel le retient : "
            "la prochaine fois, il applique directement ta correction et s'en sert pour comprendre les phrases voisines.")
        ).pack(fill="x", padx=14, pady=(0, 4))
        self.learned_holder = ctk.CTkFrame(card, fg_color="transparent")
        self.learned_holder.pack(fill="x", padx=14, pady=(0, 10))
        self._render_learned()
        KeyValueEditor(self.docs_scroll, "MES RACCOURCIS VOCAUX (macros)", "Phrase (ex. mode jeu)",
                       "Commande(s) séparées par ;  ex. coupe le son ; lance fortnite",
                       self.cfg["shortcuts"], self._save_dict).pack(fill="x", pady=(8, 8))
        ctk.CTkLabel(self.docs_scroll, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 12), text=(
            "Un raccourci associe une phrase à une ou plusieurs commandes. Exemples : « mode jeu » → "
            "« coupe le son ; lance fortnite » · « bonne nuit » → « mets l'ordinateur en veille ». "
            "Utile aussi pour les phrases que Sentinel comprend mal : ajoute-les telles qu'il les entend.")).pack(fill="x", pady=(0, 20))
        return page

    def _render_learned(self) -> None:
        if "commands" not in self.pages:
            return
        for child in self.learned_holder.winfo_children():
            child.destroy()
        items = list(self.assistant.memory.items)
        if not items:
            ctk.CTkLabel(self.learned_holder, text="Rien pour l'instant.", text_color=DIM, font=(FONT_UI, 12)).pack(anchor="w")
            return
        for item in reversed(items[-40:]):
            row = ctk.CTkFrame(self.learned_holder, fg_color="transparent")
            row.pack(fill="x", pady=2)
            meaning = f"« {item['meant']} »" if item["kind"] == "fix" else "(exemple validé : l'IA avait bien compris)"
            ctk.CTkLabel(row, text=f"« {item['heard']} »  →  {meaning}", anchor="w", justify="left", wraplength=640,
                         text_color=TEXT, font=(FONT_UI, 12)).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="✕", width=30, height=26, corner_radius=6, fg_color=PANEL2, hover_color=DANGER,
                          command=lambda ts=item.get("ts"): self._forget_one(ts)).pack(side="right")

    def _forget_one(self, ts) -> None:
        self.assistant.memory.remove(ts)
        self._render_learned()

    def _forget_learned(self) -> None:
        self.assistant.memory.clear()
        self._render_learned()

    # ---------------------------------------------------------------- apprentissage : boutons de l'accueil
    def _show_interaction(self, inter: dict) -> None:
        self._last_inter = inter
        self.lbl_last.configure(text=f"« {inter['heard'][:70]} »\n→ {inter['understood'][:90]}", text_color=TEXT)

    def _learn_ok(self) -> None:
        if not self._last_inter:
            return
        kept = self.assistant.confirm()
        self.lbl_last.configure(text=("Merci, je retiens cet exemple ✓" if kept else "Merci ✓ (c'était déjà bien géré par mes règles)"),
                                text_color=OK)

    def _teach_dialog(self) -> None:
        """Fenêtre « ce n'était pas ce que je voulais » : on saisit la bonne commande, Sentinel l'apprend."""
        last = self._last_inter
        if not last:
            return
        win = ctk.CTkToplevel(self)
        win.title("Apprendre de mon erreur")
        win.geometry("560x340")
        win.configure(fg_color=BG)
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="APPRENDRE DE MON ERREUR", font=(FONT_HEAD, 16, "bold"), text_color=self.accent).pack(anchor="w", padx=20, pady=(16, 6))
        ctk.CTkLabel(win, text=f"J'ai entendu :  « {last['heard']} »", anchor="w", justify="left", wraplength=510,
                     text_color=TEXT, font=(FONT_UI, 13)).pack(fill="x", padx=20)
        ctk.CTkLabel(win, text=f"J'ai compris :  {last['understood']}", anchor="w", justify="left", wraplength=510,
                     text_color=DIM, font=(FONT_UI, 12)).pack(fill="x", padx=20, pady=(2, 10))
        ctk.CTkLabel(win, text="Qu'est-ce que tu voulais vraiment ? (écris-le comme tu le dirais)", anchor="w",
                     text_color=TEXT, font=(FONT_UI, 13, "bold")).pack(fill="x", padx=20)
        entry = ctk.CTkEntry(win, height=36, placeholder_text="ex. ouvre Discord   ·   mets Life de Damso sur Spotify")
        entry.pack(fill="x", padx=20, pady=(6, 4))
        note = ctk.CTkLabel(win, text="", text_color=DANGER, font=(FONT_UI, 11))
        note.pack(anchor="w", padx=20)

        def learn(rerun: bool) -> None:
            meant = entry.get().strip()
            if not meant:
                note.configure(text="Écris ce que tu voulais dire.")
                return
            self.assistant.teach(last["heard"], meant, rerun)
            self.lbl_last.configure(text=f"Appris ✓  « {last['heard'][:40]} » → « {meant[:40]} »", text_color=OK)
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(10, 0))
        self._btn(row, "Apprendre et refaire", lambda: learn(True), width=190).pack(side="left")
        self._btn(row, "Apprendre seulement", lambda: learn(False), width=190).pack(side="left", padx=8)
        self._btn(row, "Annuler", win.destroy, width=90).pack(side="left")
        ctk.CTkLabel(win, justify="left", anchor="w", wraplength=510, text_color=DIM, font=(FONT_UI, 11), text=(
            "La prochaine fois que tu diras cette phrase (ou une très proche), Sentinel fera directement ce que tu as écrit ici.")
        ).pack(fill="x", padx=20, pady=(12, 0))
        entry.focus_set()

    def _debounce_docs(self) -> None:
        if self._docs_job:
            self.after_cancel(self._docs_job)
        self._docs_job = self.after(220, self._render_docs)

    def _render_docs(self) -> None:
        self._docs_job = None
        if self.docs_holder is None:
            self.docs_holder = ctk.CTkFrame(self.docs_scroll, fg_color="transparent")
            self.docs_holder.pack(fill="x")
        else:
            for child in self.docs_holder.winfo_children():
                child.destroy()
        query = normalize(self.v_search.get())
        shown = 0
        for category, icon, entries in COMMAND_DOCS:
            rows = [e for e in entries if not query or query in normalize(" ".join([category, e[0], e[2], *e[1]]))]
            if not rows:
                continue
            card = self._card(self.docs_holder)
            head = self._title(card, f"{icon}  {category.upper()}", 13)
            head.pack(anchor="w", padx=14, pady=(10, 4))
            for title, examples, note in rows:
                shown += 1
                line = ctk.CTkFrame(card, fg_color="transparent")
                line.pack(fill="x", padx=14, pady=3)
                left = ctk.CTkFrame(line, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(left, text=title, anchor="w", text_color=TEXT, font=(FONT_UI, 13, "bold")).pack(anchor="w")
                ctk.CTkLabel(left, text="  ·  ".join(f"« {e} »" for e in examples), anchor="w", justify="left", wraplength=600,
                             text_color="#7CE0FF", font=(FONT_UI, 12)).pack(anchor="w")
                if note:
                    ctk.CTkLabel(left, text=note, anchor="w", justify="left", wraplength=600, text_color=DIM,
                                 font=(FONT_UI, 11)).pack(anchor="w")
                ctk.CTkButton(line, text="▶", width=34, height=30, corner_radius=6, fg_color=PANEL2, hover_color=BORDER,
                              command=lambda ex=examples[0]: self._try_phrase(ex)).pack(side="right", padx=(8, 0))
            ctk.CTkFrame(card, height=6, fg_color="transparent").pack()
        if not shown:
            ctk.CTkLabel(self.docs_holder, text="Aucune commande ne correspond. Essaie un autre mot — ou dis-le en langage naturel, "
                         "le cerveau IA comprend.", text_color=DIM, font=(FONT_UI, 13)).pack(pady=30)

    def _try_phrase(self, phrase: str) -> None:
        self.e_test.delete(0, "end")
        self.e_test.insert(0, phrase)
        self._test_analyze()

    def _test_analyze(self) -> None:
        text = self.e_test.get().strip()
        self.lbl_test.configure(text=("→ " + self.assistant.explain(text)) if text else "", text_color=OK if text else DIM)

    def _test_run(self) -> None:
        text = self.e_test.get().strip()
        if text:
            self.lbl_test.configure(text="→ " + self.assistant.explain(text) + "   (exécuté)")
            self.assistant._on_command(text)

    # ================================================================= CERVEAU IA
    def _build_brain(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._page_title(page, "CERVEAU IA")
        c = self.cfg
        self.v_brain_on = ctk.BooleanVar(value=c["brain_enabled"])
        self.v_follow = ctk.BooleanVar(value=c["follow_up"])
        self.v_brain_url = ctk.StringVar(value=c["brain_url"])
        self.v_brain_key = ctk.StringVar(value=c["brain_api_key"])

        card = self._card(page)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 0))
        self._title(head, "ÉTAT").pack(side="left")
        self.lbl_brain = ctk.CTkLabel(head, text="Vérification…", font=(FONT_UI, 13, "bold"), text_color=DIM)
        self.lbl_brain.pack(side="left", padx=14)
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 12), text=(
            "Avec le cerveau IA, Sentinel comprend les phrases libres (« mets un truc calme pour bosser », « il pleut demain ? », "
            "« baisse le son et lance Fortnite ») et sait discuter, sans commande figée. Le modèle tourne sur TON PC via Ollama : "
            "gratuit, privé, aucune donnée envoyée. Sans lui, Sentinel garde toutes ses commandes classiques.")).pack(fill="x", padx=14, pady=(6, 6))
        self._switch(card, "Activer le cerveau IA", self.v_brain_on)
        modes = list(BRAIN_MODES.values())
        self.opt_bmode = ctk.CTkOptionMenu(self._row(card, "Quand l'utiliser"), values=modes, width=430, fg_color=PANEL2)
        self.opt_bmode.set(BRAIN_MODES.get(c["brain_mode"], modes[0]))
        self.opt_bmode.pack(side="right")
        self._switch(card, "Continuer d'écouter après une réponse de l'IA (conversation sans redire « Sentinel »)", self.v_follow)
        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

        card = self._card(page)
        self._title(card, "MODÈLE").pack(anchor="w", padx=14, pady=(12, 2))
        backends = list(BRAIN_BACKENDS.values())
        self.opt_bbackend = ctk.CTkOptionMenu(self._row(card, "Serveur"), values=backends, width=330, fg_color=PANEL2)
        self.opt_bbackend.set(BRAIN_BACKENDS.get(c["brain_backend"], backends[0]))
        self.opt_bbackend.pack(side="right")
        ctk.CTkEntry(self._row(card, "Adresse (Ollama / LM Studio)"), textvariable=self.v_brain_url, width=330).pack(side="right")
        ctk.CTkEntry(self._row(card, "Clé API (Claude, ou serveur OpenAI)"), textvariable=self.v_brain_key, width=330, show="•",
                     placeholder_text="sk-ant-…").pack(side="right")
        row = self._row(card, "Modèle utilisé")
        self._btn(row, "Actualiser", self._brain_check, width=100).pack(side="right", padx=(8, 0))
        self.opt_bmodel = ctk.CTkOptionMenu(row, values=["Automatique"], width=260, fg_color=PANEL2)
        self.opt_bmodel.set(c["brain_model"] or "Automatique")
        self.opt_bmodel.pack(side="right")
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(6, 12))
        self._btn(bar, "Enregistrer", self._brain_save, width=140).pack(side="left")
        self._btn(bar, "Effacer sa mémoire", self.assistant.brain.forget, width=170).pack(side="left", padx=10)
        self.lbl_brain_saved = ctk.CTkLabel(bar, text="", text_color=OK)
        self.lbl_brain_saved.pack(side="left", padx=8)

        card = self._card(page)
        self._title(card, "DISCUTER (test)").pack(anchor="w", padx=14, pady=(12, 2))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 4))
        self.e_chat = ctk.CTkEntry(row, placeholder_text="Écris-lui comme à une personne…", height=34)
        self.e_chat.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.e_chat.bind("<Return>", lambda _e: self._chat_send())
        self._btn(row, "Envoyer", self._chat_send, width=110).pack(side="left")
        ctk.CTkLabel(card, text="La réponse s'affiche sur l'accueil, est lue à voix haute et notée dans le Journal.",
                     text_color=DIM, font=(FONT_UI, 11), anchor="w").pack(fill="x", padx=14, pady=(0, 12))

        card = self._card(page)
        self._title(card, "OPTION : CLAUDE (beaucoup plus intelligent)").pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=TEXT, font=(FONT_UI, 12), text=(
            "Un modèle local reste limité. Pour un assistant qui comprend et raisonne comme Claude, choisis « Claude — API Anthropic » "
            "dans Serveur, colle ta clé API, choisis un modèle (Haiku : rapide et économique · Sonnet : plus fin · Opus : le plus puissant), "
            "puis Enregistrer.\n"
            "• La clé se crée sur console.anthropic.com (compte API avec du crédit : c'est distinct d'un abonnement Claude.ai). "
            "Tu paies à l'usage, et des phrases courtes coûtent très peu — vérifie les tarifs sur le site d'Anthropic.\n"
            "• Confidentialité : avec Claude, tes phrases et la liste de tes applications sont envoyées à Anthropic. "
            "La clé est enregistrée en clair dans ton dossier %APPDATA%\\Sentinel : ne partage pas ce dossier.\n"
            "• Les mêmes garde-fous s'appliquent : Claude ne peut lancer que les actions autorisées.")).pack(fill="x", padx=14, pady=(0, 12))

        card = self._card(page)
        self._title(card, "INSTALLER L'IA LOCALE (gratuit · environ 5 minutes)").pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=TEXT, font=(FONT_UI, 12), text=(
            "1. Télécharge et installe Ollama : ollama.com/download (Windows). Il se lance tout seul en arrière-plan.\n"
            "2. Ouvre l'invite de commandes (touche Windows, tape « cmd ») et télécharge un modèle :\n"
            "      PC avec 16 Go de RAM ou une carte graphique récente :   ollama pull qwen2.5:7b\n"
            "      PC plus modeste (8 Go de RAM) :   ollama pull qwen2.5:3b\n"
            "3. Reviens ici et clique sur « Actualiser » : l'état passe à « Connecté ». C'est tout.\n\n"
            "Le premier message après un moment d'inactivité peut prendre quelques secondes (chargement du modèle). "
            "Sentinel dit « je réfléchis » si ça dure. Une carte graphique accélère beaucoup ; sinon le processeur suffit.\n\n"
            "Sécurité : l'IA ne touche jamais au PC directement. Elle ne peut que choisir parmi les actions déjà prévues "
            "(liste blanche, arguments vérifiés), et les actions sensibles (veille, verrouillage, fermeture…) ne partent que "
            "si tu les as clairement demandées.")).pack(fill="x", padx=14, pady=(0, 12))
        self.after(1200, self._brain_check)
        return page

    def _brain_check(self) -> None:
        self.lbl_brain.configure(text="Vérification…", text_color=DIM)
        threading.Thread(target=lambda: self.ui_queue.put(("brain", self.assistant.brain.status(force=True, verify=True))),
                         daemon=True, name="sentinel-brain-check").start()

    def _brain_save(self) -> None:
        c = self.cfg
        c["brain_enabled"] = bool(self.v_brain_on.get())
        c["brain_mode"] = next((k for k, v in BRAIN_MODES.items() if v == self.opt_bmode.get()), "auto")
        c["brain_backend"] = next((k for k, v in BRAIN_BACKENDS.items() if v == self.opt_bbackend.get()), "ollama")
        c["brain_api_key"] = self.v_brain_key.get().strip()
        c["brain_url"] = self.v_brain_url.get().strip() or ("http://127.0.0.1:1234" if c["brain_backend"] == "openai" else "http://127.0.0.1:11434")
        model = self.opt_bmodel.get()
        c["brain_model"] = "" if model == "Automatique" else model
        c["follow_up"] = bool(self.v_follow.get())
        c.save()
        self.lbl_brain_saved.configure(text="Enregistré ✓")
        self.after(2500, lambda: self.lbl_brain_saved.configure(text=""))
        self.hud.set_text("badge", self._badge())
        self._brain_check()

    def _show_brain(self, status: dict) -> None:
        self._brain = status
        if "brain" not in self.pages:
            self.hud.set_text("badge", self._badge())
            return
        ok = bool(status.get("ok")) and self.cfg["brain_enabled"]
        text = status.get("message", "") if self.cfg["brain_enabled"] else "Désactivé"
        self.lbl_brain.configure(text=("● " if ok else "○ ") + text, text_color=OK if ok else DANGER if self.cfg["brain_enabled"] else DIM)
        self.stats["Cerveau IA"].configure(text=("En ligne · " + status.get("model", "")) if ok else
                                           ("Désactivé" if not self.cfg["brain_enabled"] else "Hors ligne"),
                                           text_color=OK if ok else DIM)
        self.hud.set_text("badge", self._badge())
        models = status.get("models") or []
        self.opt_bmodel.configure(values=["Automatique"] + models)

    def _chat_send(self) -> None:
        text = self.e_chat.get().strip()
        if text:
            self.e_chat.delete(0, "end")
            self.assistant._on_command(text)

    # ===================================================================== RÉPONSES
    def _build_replies(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._page_title(page, "RÉPONSES VOCALES")
        c = self.cfg

        card = self._card(page)
        self.v_style = ctk.StringVar(value=STYLES.get(c["reply_style"], STYLES["jarvis"]))
        row = self._row(card, "Style de réponse")
        ctk.CTkOptionMenu(row, values=list(STYLES.values()), variable=self.v_style, width=330, fg_color=PANEL2,
                          command=self._on_style).pack(side="right")
        self.v_name = ctk.StringVar(value=c["user_name"])
        row = self._row(card, "Comment Sentinel t'appelle (prénom, « monsieur »…)")
        ctk.CTkEntry(row, textvariable=self.v_name, width=330, placeholder_text="laisser vide = rien").pack(side="right")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(6, 14))
        self._btn(row, "Enregistrer", self._save_replies, width=140).pack(side="left")
        self._btn(row, "Écouter un exemple", lambda: self.assistant.speaker.say(preview(self.cfg, "ack")), width=190).pack(side="left", padx=10)
        self.lbl_replies_saved = ctk.CTkLabel(row, text="", text_color=OK)
        self.lbl_replies_saved.pack(side="left", padx=8)

        card = self._card(page)
        self._title(card, "MES PROPRES PHRASES").pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=680, text_color=DIM, font=(FONT_UI, 12), text=(
            "Laisse un champ vide pour garder la phrase du style choisi (affichée en grisé). "
            "Plusieurs variantes ? Sépare-les par « | » : Sentinel en choisit une au hasard. "
            "Les mots entre accolades, comme {p}, sont remplacés automatiquement ; {appel} ajoute ton prénom. "
            "Le bouton ▶ prononce la phrase.")).pack(fill="x", padx=14, pady=(0, 6))
        self.reply_entries: dict[str, ctk.CTkEntry] = {}
        for key, label, args in editable():
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            hint = "  " + " ".join("{" + a + "}" for a in args) if args else ""
            ctk.CTkLabel(row, text=label + hint, width=250, anchor="w", justify="left", wraplength=240,
                         text_color=TEXT, font=(FONT_UI, 12)).pack(side="left")
            entry = ctk.CTkEntry(row, placeholder_text=default_text(self.cfg, key))
            custom = c["custom_replies"].get(key, "")
            if custom:
                entry.insert(0, custom)
            entry.pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkButton(row, text="▶", width=34, fg_color=PANEL2,
                          command=lambda k=key, e=entry: self.assistant.speaker.say(preview(self.cfg, k, e.get()))).pack(side="left")
            self.reply_entries[key] = entry
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 14))
        self._btn(row, "Enregistrer mes phrases", self._save_replies, width=220).pack(side="left")
        self._btn(row, "Tout réinitialiser", self._reset_replies, width=170).pack(side="left", padx=10)
        return page

    def _on_style(self, label: str) -> None:
        self.cfg["reply_style"] = next((k for k, v in STYLES.items() if v == label), "jarvis")
        self.cfg.save()
        for key, entry in self.reply_entries.items():         # rafraîchit les phrases grisées
            entry.configure(placeholder_text=default_text(self.cfg, key))

    def _save_replies(self) -> None:
        c = self.cfg
        c["user_name"] = self.v_name.get().strip()
        c["reply_style"] = next((k for k, v in STYLES.items() if v == self.v_style.get()), "jarvis")
        custom = c["custom_replies"]
        for key, entry in self.reply_entries.items():
            text = entry.get().strip()
            if text:
                custom[key] = text
            else:
                custom.pop(key, None)
        c.save()
        self.lbl_replies_saved.configure(text="Enregistré ✓")
        self.after(2500, lambda: self.lbl_replies_saved.configure(text=""))

    def _reset_replies(self) -> None:
        self.cfg["custom_replies"].clear()
        for entry in self.reply_entries.values():
            entry.delete(0, "end")
        self.cfg.save()

    # ------------------------------------------------------------ horloge / météo
    def _tick(self) -> None:
        if self._closing:
            return
        try:
            if self.winfo_viewable():
                now = datetime.datetime.now()
                self.hud.set_text("clock", now.strftime("%H:%M:%S"))
                self.hud.set_text("date", fr_date(now.date()).capitalize())
                if self.cfg["hud_fx"] and self.current_page == "home":
                    cpu, ram = cpu_percent(), ram_percent()
                    bar = lambda p: "█" * round(p / 100 * 6) + "░" * (6 - round(p / 100 * 6))
                    self.hud.set_text("tele", f"CPU {bar(cpu)} {cpu:3.0f}%   RAM {bar(ram)} {ram:3.0f}%")
                elif not self.cfg["hud_fx"]:
                    self.hud.set_text("tele", "")
                items = self.assistant.timers.snapshot()
                if items:
                    lines = [f"{format_clock(t.left)}  {t.label or format_duration(t.seconds)}" for t in items[:4]]
                    self.lbl_timers.configure(text="\n".join(lines), text_color=TEXT)
                else:
                    self.lbl_timers.configure(text="Aucun en cours", text_color=DIM)
        except Exception:
            log.exception("erreur d'horloge")
        self.after(1000, self._tick)

    def _show_weather(self, data, reason: str) -> None:
        if data:
            self.lbl_wx_main.configure(text=f"{symbol(data['code'])}  {data['temp']}°C")
            sub = f"{data['city']} · {data['desc']}"
            if data.get("tmin") is not None and data.get("tmax") is not None:
                sub += f"\nmin {data['tmin']}° · max {data['tmax']}°"
            if data.get("rain") is not None:
                sub += f" · pluie {data['rain']} %"
            self.lbl_wx_sub.configure(text=sub)
        else:
            self.lbl_wx_main.configure(text="—")
            self.lbl_wx_sub.configure(text={
                "no_city": "Indique ta ville dans Paramètres → Actions.",
                "city_unknown": "Ville introuvable, vérifie l'orthographe.",
                "network": "Météo indisponible (pas de connexion ?).",
            }.get(reason, ""))

    # =================================================================== PARAMÈTRES
    def _slider(self, parent, label, var, lo, hi, steps, fmt):
        row = self._row(parent, label)
        value = ctk.CTkLabel(row, text=fmt(var.get()), width=64, text_color=TEXT)
        value.pack(side="right")
        s = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, variable=var, width=230,
                          command=lambda v: value.configure(text=fmt(v)))
        self._acc_reg(s, "progress_color", "button_color")
        s.pack(side="right", padx=8)

    def _switch(self, parent, label, var):
        row = self._row(parent, label)
        sw = ctk.CTkSwitch(row, text="", variable=var, onvalue=True, offvalue=False)
        self._acc_reg(sw, "progress_color")
        sw.pack(side="right")

    def _build_settings(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._page_title(page, "PARAMÈTRES")
        c = self.cfg

        self.v_wake = ctk.StringVar(value=c["wake_word"])
        self.v_alias = ctk.StringVar(value=", ".join(c["wake_aliases"]))
        self.v_timeout = ctk.DoubleVar(value=c["listen_timeout"])
        self.v_step = ctk.DoubleVar(value=c["volume_step"])
        self.v_rate = ctk.DoubleVar(value=c["tts_rate"])
        self.v_pitch = ctk.DoubleVar(value=c["tts_pitch"])
        self.v_tvol = ctk.DoubleVar(value=c["tts_volume"])
        self.v_tts = ctk.BooleanVar(value=c["tts_enabled"])
        self.v_show = ctk.BooleanVar(value=c["show_heard"])
        self.v_tray = ctk.BooleanVar(value=c["minimize_to_tray"])
        self.v_auto = ctk.BooleanVar(value=c["start_with_windows"])
        self.v_city = ctk.StringVar(value=c["weather_city"])
        self.v_bstep = ctk.DoubleVar(value=c["brightness_step"])

        # -- écoute
        card = self._card(page)
        self._title(card, "ÉCOUTE").pack(anchor="w", padx=14, pady=(12, 2))
        row = self._row(card, "Mot déclencheur")
        ctk.CTkEntry(row, textvariable=self.v_wake, width=260).pack(side="right")
        row = self._row(card, "Variantes reconnues (séparées par des virgules)")
        ctk.CTkEntry(row, textvariable=self.v_alias, width=260).pack(side="right")
        self._slider(card, "Durée d'écoute après le mot seul", self.v_timeout, 3, 15, 12, lambda v: f"{float(v):.0f} s")
        mics = ["Micro par défaut"] + list_mics()
        self.v_mic = ctk.StringVar(value=next((m for m in mics if c["mic_device"] is not None and m.startswith(f"{c['mic_device']}:")), mics[0]))
        row = self._row(card, "Microphone")
        ctk.CTkOptionMenu(row, values=mics, variable=self.v_mic, width=340, fg_color=PANEL2).pack(side="right")
        self._switch(card, "Journaliser tout ce qui est entendu (utile pour régler les variantes)", self.v_show)
        self.opt_asr = ctk.CTkOptionMenu(self._row(card, "Reconnaissance vocale"), values=list(ASR_MODES.values()),
                                         width=340, fg_color=PANEL2)
        self.opt_asr.set(ASR_MODES[bool(c["asr_whisper"])])
        self.opt_asr.pack(side="right")
        self.opt_wmodel = ctk.CTkOptionMenu(self._row(card, "Modèle Whisper"), values=list(WHISPER_MODELS.values()),
                                            width=340, fg_color=PANEL2)
        self.opt_wmodel.set(WHISPER_MODELS.get(c["whisper_model"], WHISPER_MODELS["small"]))
        self.opt_wmodel.pack(side="right")
        self.lbl_asr = ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 11), text=(
            "Whisper re-transcrit avec beaucoup plus de précision les phrases adressées à Sentinel. Il faut d'abord "
            "installer « pip install faster-whisper » ; le modèle se télécharge une seule fois au premier lancement. "
            "Si Whisper échoue, Sentinel garde Vosk."))
        self.lbl_asr.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

        # -- voix
        card = self._card(page)
        self._title(card, "VOIX").pack(anchor="w", padx=14, pady=(12, 2))
        self._switch(card, "Réponses vocales", self.v_tts)
        row = self._row(card, "Moteur vocal")
        self.opt_tts = ctk.CTkOptionMenu(row, values=list(TTS_ENGINES.values()), width=340, fg_color=PANEL2)
        self.opt_tts.set(TTS_ENGINES.get(c["tts_engine"], TTS_ENGINES["auto"]))
        self.opt_tts.pack(side="right")
        row = self._row(card, "Voix neuronale (masculine par défaut)")
        self.opt_edge = ctk.CTkOptionMenu(row, values=list(EDGE_VOICES.values()), width=340, fg_color=PANEL2)
        self.opt_edge.set(EDGE_VOICES.get(c["tts_edge_voice"], EDGE_VOICES["fr-FR-HenriNeural"]))
        self.opt_edge.pack(side="right")
        self._slider(card, "Hauteur de la voix", self.v_pitch, -20, 20, 40, lambda v: f"{float(v):+.0f} Hz")
        self._slider(card, "Vitesse", self.v_rate, -5, 5, 10, lambda v: f"{float(v):+.0f}")
        self._slider(card, "Volume de la voix", self.v_tvol, 0, 100, 20, lambda v: f"{float(v):.0f} %")
        voices = ["Automatique (français)"] + list_voices()
        self.v_voice = ctk.StringVar(value=c["tts_voice"] if c["tts_voice"] in voices else voices[0])
        row = self._row(card, "Voix Windows de secours (sans Internet)")
        ctk.CTkOptionMenu(row, values=voices, variable=self.v_voice, width=340, fg_color=PANEL2).pack(side="right")
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 11), text=(
            "La voix neuronale (Microsoft Edge, gratuite) est bien plus naturelle que la voix Windows mais demande Internet. "
            "Sans connexion, Sentinel bascule seul sur la voix Windows, puis revient.")).pack(fill="x", padx=14, pady=(2, 10))

        # -- actions
        card = self._card(page)
        self._title(card, "ACTIONS").pack(anchor="w", padx=14, pady=(12, 2))
        self._slider(card, "Pas du volume (« monte / baisse le son »)", self.v_step, 5, 25, 4, lambda v: f"{float(v):.0f} %")
        self._slider(card, "Pas de la luminosité (« baisse la luminosité »)", self.v_bstep, 5, 25, 4, lambda v: f"{float(v):.0f} %")
        row = self._row(card, "Ville pour la météo")
        ctk.CTkEntry(row, textvariable=self.v_city, width=260, placeholder_text="ex. Lille").pack(side="right")
        self.v_engine = ctk.StringVar(value=ENGINES.get(c["search_engine"], "Google"))
        row = self._row(card, "Moteur de recherche")
        ctk.CTkOptionMenu(row, values=list(ENGINES.values()), variable=self.v_engine, width=200, fg_color=PANEL2).pack(side="right")
        ctk.CTkFrame(card, height=8, fg_color="transparent").pack()

        # -- personnalisation
        card = self._card(page)
        self._title(card, "PERSONNALISATION").pack(anchor="w", padx=14, pady=(12, 2))
        self.v_aname = ctk.StringVar(value=c["assistant_name"])
        ctk.CTkEntry(self._row(card, "Nom de l'assistant (affiché, et donné à l'IA)"), textvariable=self.v_aname, width=260,
                     placeholder_text=(c["wake_word"] or "sentinel").capitalize()).pack(side="right")
        themes = list(THEMES)
        self.opt_theme = ctk.CTkOptionMenu(self._row(card, "Thème (couleurs du fond)"), values=themes, width=260, fg_color=PANEL2)
        self.opt_theme.set(c["theme"] if c["theme"] in THEMES else themes[0])
        self.opt_theme.pack(side="right")
        self.v_custom_bg = ctk.StringVar(value=c["custom_bg"])
        ctk.CTkEntry(self._row(card, "Couleur de fond libre (#RRGGBB, sombre) — remplace le thème"), textvariable=self.v_custom_bg,
                     width=260, placeholder_text="ex. #0B1020").pack(side="right")
        self.v_accent = ctk.StringVar(value=c["accent"])
        ctk.CTkOptionMenu(self._row(card, "Couleur d'accent"), values=list(ACCENTS), variable=self.v_accent, width=260,
                          fg_color=PANEL2).pack(side="right")
        self.v_custom_accent = ctk.StringVar(value=c["custom_accent"])
        ctk.CTkEntry(self._row(card, "Couleur d'accent libre (#RRGGBB) — remplace la précédente"), textvariable=self.v_custom_accent,
                     width=260, placeholder_text="ex. #FF3DCB").pack(side="right")
        self.opt_hud = ctk.CTkOptionMenu(self._row(card, "Fond du HUD"), values=list(HUD_STYLES.values()), width=260, fg_color=PANEL2)
        self.opt_hud.set(HUD_STYLES.get(c["hud_bg"], HUD_STYLES["stars"]))
        self.opt_hud.pack(side="right")
        self.v_hudfx = ctk.BooleanVar(value=c["hud_fx"])
        self._switch(card, "Effets du HUD (balayage lumineux, télémétrie CPU / RAM)", self.v_hudfx)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 12))
        self._btn(row, "Enregistrer et redémarrer", self._apply_and_restart, width=220).pack(side="left")
        ctk.CTkLabel(row, text="L'accent et le fond du HUD s'appliquent dès « Enregistrer » ; le thème, la couleur de fond "
                     "et le nom demandent un redémarrage.", text_color=DIM, font=(FONT_UI, 11), wraplength=470, justify="left"
                     ).pack(side="left", padx=12)

        # -- mises à jour
        card = self._card(page)
        self._title(card, "MISES À JOUR").pack(anchor="w", padx=14, pady=(12, 2))
        self._release = None
        self.v_upd = ctk.BooleanVar(value=c["update_check"])
        self.lbl_update = ctk.CTkLabel(card, text=f"Version installée : {__version__}", anchor="w", justify="left",
                                       wraplength=740, text_color=TEXT, font=(FONT_UI, 13))
        self.lbl_update.pack(fill="x", padx=14, pady=(2, 2))
        self.lbl_notes = ctk.CTkLabel(card, text="", anchor="w", justify="left", wraplength=740, text_color=DIM, font=(FONT_UI, 12))
        self.lbl_notes.pack(fill="x", padx=14)
        self.bar_update = ctk.CTkProgressBar(card)
        self._acc_reg(self.bar_update, "progress_color")
        self.bar_update.set(0)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 4))
        self._btn(row, "Rechercher une mise à jour", self._update_check, width=220).pack(side="left")
        self.btn_upd_install = self._btn(row, "Mettre à jour et redémarrer", self._update_install, width=230)
        self.btn_upd_install.pack(side="left", padx=8)
        self.btn_upd_install.configure(state="disabled")
        self.btn_upd_back = self._btn(row, "Version précédente", self._update_rollback, width=170)
        self.btn_upd_back.pack(side="left")
        self._switch(card, "Chercher une mise à jour au démarrage (une fois par jour)", self.v_upd)
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 11), text=(
            "Rien ne s'installe sans ton clic. Tes réglages, ce que Sentinel a appris et tes connexions sont conservés. "
            "L'ancienne version est gardée pour pouvoir revenir en arrière.")).pack(fill="x", padx=14, pady=(0, 10))

        # -- profil & partage
        card = self._card(page)
        self._title(card, "PROFIL & PARTAGE (pour tes amis)").pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, justify="left", anchor="w", wraplength=740, text_color=DIM, font=(FONT_UI, 12), text=(
            "Exporte tes réglages (nom, mot déclencheur, thème, raccourcis vocaux, alias d'applis, playlists, phrases, voix…) "
            "dans un fichier à envoyer à un ami : il l'importe et retrouve ta configuration. Aucune clé ni identifiant n'y figure. "
            "Chaque personne garde ses propres réglages, sa mémoire d'apprentissage et son micro.")).pack(fill="x", padx=14, pady=(0, 6))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(2, 12))
        self._btn(row, "Exporter mon profil…", self._export_profile, width=190).pack(side="left")
        self._btn(row, "Importer un profil…", self._import_profile, width=190).pack(side="left", padx=8)
        self.lbl_profile = ctk.CTkLabel(row, text="", font=(FONT_UI, 12), text_color=OK)
        self.lbl_profile.pack(side="left", padx=8)

        # -- système
        card = self._card(page)
        self._title(card, "SYSTÈME").pack(anchor="w", padx=14, pady=(12, 2))
        self._switch(card, "Réduire dans la zone de notification à la fermeture", self.v_tray)
        self._switch(card, "Lancer Sentinel au démarrage de Windows", self.v_auto)
        ctk.CTkFrame(card, height=8, fg_color="transparent").pack()

        KeyValueEditor(page, "CORRECTIONS VOCALES", "Ce que Sentinel entend (ex. dans so)",
                       "Ce que tu veux dire (ex. damso)", c["corrections"], self._save_dict).pack(fill="x", pady=(0, 12))

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 20))
        self._btn(bar, "Enregistrer", self._apply_settings, width=160).pack(side="left")
        self._btn(bar, "Enregistrer + tester la voix", self._apply_and_speak, width=230).pack(side="left", padx=10)
        self.lbl_saved = ctk.CTkLabel(bar, text="", text_color=OK)
        self.lbl_saved.pack(side="left", padx=8)
        return page

    def _apply_settings(self) -> None:
        c = self.cfg
        c["wake_word"] = self.v_wake.get().strip().lower() or "sentinel"
        c["wake_aliases"] = [a.strip().lower() for a in self.v_alias.get().split(",") if a.strip()]
        c["listen_timeout"] = int(self.v_timeout.get())
        c["volume_step"] = int(self.v_step.get())
        c["brightness_step"] = int(self.v_bstep.get())
        city = self.v_city.get().strip()
        city_changed = city != c["weather_city"]
        c["weather_city"] = city
        c["tts_rate"] = int(self.v_rate.get())
        c["tts_volume"] = int(self.v_tvol.get())
        c["tts_enabled"] = bool(self.v_tts.get())
        c["show_heard"] = bool(self.v_show.get())
        c["minimize_to_tray"] = bool(self.v_tray.get())
        c["accent"] = self.v_accent.get()
        c["assistant_name"] = self.v_aname.get().strip()
        c["theme"] = self.opt_theme.get()
        invalid = False
        for key, var in (("custom_bg", self.v_custom_bg), ("custom_accent", self.v_custom_accent)):
            value = var.get().strip()
            if value and not is_hex(value):
                invalid = True
                value = ""
            c[key] = value
        c["hud_bg"] = next((k for k, v in HUD_STYLES.items() if v == self.opt_hud.get()), "stars")
        c["hud_fx"] = bool(self.v_hudfx.get())
        c["update_check"] = bool(self.v_upd.get())
        voice = self.v_voice.get()
        c["tts_voice"] = "" if voice.startswith("Automatique") else voice
        asr_on = self.opt_asr.get() == ASR_MODES[True]
        wmodel = next((k for k, v in WHISPER_MODELS.items() if v == self.opt_wmodel.get()), "small")
        asr_changed = asr_on != c["asr_whisper"] or wmodel != c["whisper_model"]
        c["asr_whisper"], c["whisper_model"] = asr_on, wmodel
        c["tts_engine"] = next((k for k, v in TTS_ENGINES.items() if v == self.opt_tts.get()), "auto")
        c["tts_edge_voice"] = next((k for k, v in EDGE_VOICES.items() if v == self.opt_edge.get()), "fr-FR-HenriNeural")
        c["tts_pitch"] = int(self.v_pitch.get())
        self.assistant.speaker._edge_down_until = 0.0             # on retente la voix neuronale
        c["search_engine"] = next((k for k, v in ENGINES.items() if v == self.v_engine.get()), "google")

        mic = self.v_mic.get()
        new_mic = int(mic.split(":")[0]) if ":" in mic and mic.split(":")[0].isdigit() else None
        mic_changed = new_mic != c["mic_device"]
        c["mic_device"] = new_mic

        auto = bool(self.v_auto.get())
        if auto != c["start_with_windows"]:
            try:
                set_autostart(auto)
            except Exception:
                log.exception("impossible de modifier le démarrage automatique")
                auto = c["start_with_windows"]
                self.v_auto.set(auto)
        c["start_with_windows"] = auto
        c.save()

        if mic_changed:
            self.assistant.listener.restart_stream()
        if asr_changed:
            self.assistant.listener.asr.reset()
        if city_changed:
            self.lbl_wx_sub.configure(text="Chargement…")
            self.assistant.refresh_weather()
        self.set_accent(c["accent"])
        self.hud.set_text("hint", self._hint())
        self.stats["Voix"].configure(text=self._voice_name())
        self.hud.set_text("badge", self._badge())
        self.hud.set_style(c["hud_bg"], c["hud_fx"])
        self.lbl_saved.configure(text="Couleur ignorée : format #RRGGBB attendu (ex. #0B1020)" if invalid else "Enregistré ✓",
                                 text_color=DANGER if invalid else OK)
        self.after(2500, lambda: self.lbl_saved.configure(text=""))

    def _show_asr(self, state: str, detail: str) -> None:
        self._last_asr = (state, detail)
        self.stats["Whisper"].configure(text={
            "off": "désactivé", "loading": f"chargement {detail}…", "ready": f"prêt ✓ ({detail})", "error": "indisponible",
        }.get(state, state), text_color={"ready": OK, "error": DANGER}.get(state, DIM))
        if state == "error":
            self._append_log("error", f"Whisper : {detail}")
        elif state in ("ready", "loading"):
            self._append_log("info", f"Whisper : {'prêt ✓ (' + detail + ')' if state == 'ready' else 'chargement ' + detail + '…'}")
        if "settings" not in self.pages:
            return
        text, color = {
            "off": ("désactivé", DIM), "loading": (f"chargement {detail}… (1re fois : téléchargement)", DIM),
            "ready": (f"prêt ✓ ({detail})", OK), "error": ("indisponible", DANGER),
        }.get(state, (state, DIM))
        self.stats["Whisper"].configure(text=text, text_color=color)
        if state == "error":
            self._append_log("error", f"Whisper : {detail}")
        elif state in ("ready", "loading"):
            self._append_log("info", f"Whisper : {text}")
        self.lbl_asr.configure(text=("Whisper : " + text) if state != "error" else f"Whisper indisponible — {detail}",
                               text_color=DANGER if state == "error" else DIM)

    def _replay_asr(self) -> None:
        if self._last_asr:
            state, detail = self._last_asr
            text = {"off": "désactivé", "loading": f"chargement {detail}…", "ready": f"prêt ✓ ({detail})",
                   "error": "indisponible"}.get(state, state)
            self.lbl_asr.configure(text=("Whisper : " + text) if state != "error" else f"Whisper indisponible — {detail}",
                                   text_color=DANGER if state == "error" else DIM)

    def _apply_and_restart(self) -> None:
        self._apply_settings()
        restart_app()
        self._quit()

    # ---------------------------------------------------------------- mises à jour
    def _update_check(self) -> None:
        updater = self.assistant.updater
        if not updater.enabled:
            self.lbl_update.configure(text="Les mises à jour ne sont pas encore configurées (dépôt GitHub manquant).", text_color=DANGER)
            return
        self.lbl_update.configure(text="Recherche en cours…", text_color=DIM)

        def work() -> None:
            try:
                rel = updater.check()
                self.ui_queue.put(("update", "available", rel) if rel else ("update", "uptodate", None))
            except UpdateError as exc:
                self.ui_queue.put(("update", "error", str(exc)))

        threading.Thread(target=work, daemon=True, name="sentinel-update-check").start()

    def _update_install(self) -> None:
        rel = self._release
        if not rel:
            return
        self.btn_upd_install.configure(state="disabled")
        self.lbl_update.configure(text=f"Téléchargement de la version {rel.version}…", text_color=DIM)
        updater = self.assistant.updater

        def work() -> None:
            try:
                updater.install(rel, lambda done, total: self.ui_queue.put(("update", "progress", (done, total))))
                self.ui_queue.put(("update", "installed", None))
            except UpdateError as exc:
                self.ui_queue.put(("update", "error", str(exc)))
            except Exception as exc:
                log.exception("mise à jour en échec")
                self.ui_queue.put(("update", "error", f"Erreur inattendue : {exc}"))

        threading.Thread(target=work, daemon=True, name="sentinel-update-install").start()

    def _update_rollback(self) -> None:
        try:
            self.assistant.updater.rollback()
            self._show_update("installed", None)
        except UpdateError as exc:
            self._show_update("error", str(exc))

    def _show_update(self, state: str, payload) -> None:
        self._last_update = (state, payload)
        if state == "available":
            self._release = payload
            self.lbl_version.configure(text=f"● v{payload.version} dispo", text_color=self.accent)
            self._append_log("info", f"Mise à jour disponible : {payload.version}")
        elif state == "uptodate":
            self._release = None
        elif state == "installed":
            # doit se déclencher même si la page Paramètres n'a jamais été ouverte
            self.after(800, self._quit)
            self.after(6000, lambda: os._exit(0))                  # filet de sécurité : le script attend la fin du processus
        if "settings" not in self.pages:
            return
        if state == "available":
            self.lbl_update.configure(text=f"Nouvelle version disponible : {payload.version} (tu as la {__version__})", text_color=OK)
            self.lbl_notes.configure(text=payload.notes[:600])
            self.btn_upd_install.configure(state="normal")
        elif state == "uptodate":
            self.lbl_update.configure(text=f"Tu es à jour ✓ (version {__version__})", text_color=OK)
            self.lbl_notes.configure(text="")
            self.btn_upd_install.configure(state="disabled")
        elif state == "progress":
            done, total = payload
            self.bar_update.pack(fill="x", padx=14, pady=(4, 0))
            self.bar_update.set(done / total if total else 0.5)
        elif state == "installed":
            self.lbl_update.configure(text="Installation en cours : Sentinel va se fermer puis se relancer tout seul…", text_color=OK)
        elif state == "error":
            self.btn_upd_install.configure(state="normal" if self._release else "disabled")
            self.lbl_update.configure(text=str(payload), text_color=DANGER)

    def _replay_update(self) -> None:
        if self._last_update:
            self._show_update(*self._last_update)

    def _export_profile(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="mon-profil-sentinel.json",
                                            filetypes=[("Profil Sentinel", "*.json")])
        if path:
            try:
                export_profile(self.cfg, path)
                self.lbl_profile.configure(text="Profil exporté ✓", text_color=OK)
            except OSError as exc:
                self.lbl_profile.configure(text=f"Échec : {exc}", text_color=DANGER)

    def _import_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Profil Sentinel", "*.json")])
        if not path:
            return
        try:
            count = import_profile(self.cfg, path)
            self.lbl_profile.configure(text=f"{count} réglages importés ✓ — redémarre Sentinel pour tout appliquer", text_color=OK)
        except Exception as exc:
            self.lbl_profile.configure(text=f"Fichier invalide : {exc}", text_color=DANGER)

    def _apply_and_speak(self) -> None:
        self._apply_settings()
        self.assistant.speaker.say("Paramètres enregistrés. Voici ma voix.")

    def set_accent(self, name: str) -> None:
        self.accent = self._accent_color(self.cfg)
        for widget, options in self._acc:
            self._paint(widget, options)
        self._paint_nav()
        self.hud.set_accent(self.accent)

    # ===================================================================== JOURNAL
    def _build_log(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self._page_title(page, "JOURNAL")
        self.txt_log = ctk.CTkTextbox(page, fg_color=PANEL, text_color=TEXT, font=(FONT_MONO, 12), corner_radius=12)
        self.txt_log.pack(fill="both", expand=True)
        for tag, color in (("heard", DIM), ("cmd", "#7CE0FF"), ("reply", OK), ("info", DIM), ("error", DANGER)):
            self.txt_log.tag_config(tag, foreground=color)
        self.txt_log.configure(state="disabled")
        self._btn(page, "Effacer", self._clear_log, width=100).pack(anchor="e", pady=(8, 0))
        for stamp, kind, text in self._log_buffer:                 # rattrape ce qui s'est passé avant que la page existe
            self._write_log(stamp, kind, text)
        return page

    def _append_log(self, kind: str, text: str) -> None:
        prefix = {"heard": "entendu ", "cmd": "COMMANDE", "reply": "réponse ", "info": "info    ", "error": "ERREUR  "}.get(kind, kind)
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((stamp, kind, text))
        del self._log_buffer[:-600]
        if "log" in self.pages:                                    # la page n'existe que si elle a déjà été ouverte
            self._write_log(stamp, kind, text, prefix)

    def _write_log(self, stamp: str, kind: str, text: str, prefix: str | None = None) -> None:
        prefix = prefix or {"heard": "entendu ", "cmd": "COMMANDE", "reply": "réponse ", "info": "info    ", "error": "ERREUR  "}.get(kind, kind)
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{stamp}  {prefix}  {text}\n", kind)
        if int(self.txt_log.index("end-1c").split(".")[0]) > 600:
            self.txt_log.delete("1.0", "50.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_buffer.clear()
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # =============================================================== événements
    def _set_state(self, state: str) -> None:
        self.state_key = state
        self.hud.set_text("state", STATE_TEXT.get(state, state.upper()))

    def _poll_queue(self) -> None:
        try:
            while True:
                self._handle(self.ui_queue.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            log.exception("erreur de traitement d'événement UI")
        if not self._closing:
            self.after(60, self._poll_queue)

    def _handle(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "state":
            self._set_state(ev[1])
        elif kind == "log":
            self._append_log(ev[1], ev[2])
            if ev[1] == "cmd":
                self.hud.set_text("heard", f"« {ev[2]} »")
                self.hud.set_text("reply", "")
            elif ev[1] == "reply":
                self.hud.set_text("reply", ev[2])
        elif kind == "ready":
            self.stats["Micro"].configure(text="En ligne ✓", text_color=OK)
            name = ev[1] if len(ev) > 1 else ""
            self.stats["Modèle vocal"].configure(text=f"Chargé ✓ {name}".strip(), text_color=OK)
            self.card_model.pack_forget()
        elif kind == "model_missing":
            self._set_state("nomodel")
            self.stats["Modèle vocal"].configure(text="Manquant", text_color=DANGER)
            self.card_model.pack(fill="x", padx=16, pady=12)
        elif kind == "model_progress":
            self.bar_dl.set(ev[1])
        elif kind == "model_done":
            self.card_model.pack_forget()
            self._set_state("loading")
        elif kind == "model_error":
            self.btn_dl.configure(state="normal", text="Réessayer")
            self._append_log("error", f"Téléchargement du modèle : {ev[1]}")
        elif kind == "apps_indexed":
            self.stats["Applications"].configure(text=f"{ev[1]} indexées")
            self.lbl_scan.configure(text=f"{ev[1]} applications et programmes connus")
        elif kind == "files_indexed":
            self.stats["Fichiers"].configure(text=f"{ev[1]} indexés")
        elif kind == "brain":
            self._show_brain(ev[1])
        elif kind == "update":
            self._show_update(ev[1], ev[2] if len(ev) > 2 else None)
        elif kind == "interaction":
            self._show_interaction(ev[1])
        elif kind == "learned":
            self._render_learned()
        elif kind == "asr":
            self._show_asr(ev[1], ev[2] if len(ev) > 2 else "")
        elif kind == "spotify_status":
            self._show_spotify(ev[1])
        elif kind == "weather":
            self._show_weather(ev[1], ev[2])
        elif kind == "show":
            if self.web:
                self.web.open_window()                 # l'icône de la zone de notification ouvre la nouvelle interface
            else:
                self.deiconify()
                self.lift()
                self.focus_force()
        elif kind == "show_classic":
            self.deiconify()
            self.lift()
            self.focus_force()
            if len(ev) > 1 and ev[1] in self.pages:
                self.show_page(ev[1])
        elif kind == "set_listen":
            (self.sw_listen.select if ev[1] else self.sw_listen.deselect)()
            self._toggle_listen()
        elif kind == "toggle_listen":
            self.sw_listen.toggle()
        elif kind == "quit":
            self._quit()

    def _animate(self) -> None:
        if self._closing:
            return
        try:
            if self.current_page == "home" and self.winfo_viewable():
                self.hud.draw(self.state_key, self.assistant.level)
        except Exception:
            log.exception("erreur d'animation")
        self.after(33, self._animate)

    # ============================================================== fermeture
    def _on_close(self) -> None:
        if self.cfg["minimize_to_tray"]:
            self.withdraw() if self.tray else self.iconify()
        else:
            self._quit()

    def _quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            if self.web:
                self.web.stop()
            self.assistant.shutdown()
            if self.tray:
                self.tray.stop()
        finally:
            self.destroy()
