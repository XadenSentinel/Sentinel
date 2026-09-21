"""Widgets réutilisables."""
from __future__ import annotations

from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from .theme import DIM, FONT_UI, PANEL, PANEL2, TEXT


class KeyValueEditor(ctk.CTkFrame):
    """Petit éditeur « nom -> valeur » (playlists, alias d'applications, corrections).

    Modifie directement le dictionnaire reçu et appelle `on_change` (sauvegarde).
    """

    def __init__(self, master, title: str, key_hint: str, value_hint: str, data: dict,
                 on_change: Callable[[], None], browse: bool = False) -> None:
        super().__init__(master, fg_color=PANEL, corner_radius=12)
        self.data = data
        self.on_change = on_change

        ctk.CTkLabel(self, text=title, font=(FONT_UI, 13, "bold"), text_color=TEXT).pack(anchor="w", padx=14, pady=(12, 4))
        self.rows = ctk.CTkFrame(self, fg_color="transparent")
        self.rows.pack(fill="x", padx=10)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=10, pady=(6, 12))
        self.e_key = ctk.CTkEntry(form, placeholder_text=key_hint, width=200)
        self.e_key.pack(side="left", padx=(4, 6))
        self.e_val = ctk.CTkEntry(form, placeholder_text=value_hint)
        self.e_val.pack(side="left", fill="x", expand=True, padx=(0, 6))
        if browse:
            ctk.CTkButton(form, text="Parcourir…", width=90, fg_color=PANEL2, command=self._browse).pack(side="left", padx=(0, 6))
        ctk.CTkButton(form, text="Ajouter", width=80, fg_color=PANEL2, command=self._add).pack(side="left")
        self._refresh()

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Choisir un programme",
            filetypes=[("Programmes et raccourcis", "*.exe *.lnk *.bat *.url"), ("Tous les fichiers", "*.*")])
        if path:
            self.e_val.delete(0, "end")
            self.e_val.insert(0, path)

    def _add(self) -> None:
        key, val = self.e_key.get().strip().lower(), self.e_val.get().strip()
        if not key or not val:
            return
        self.data[key] = val
        self.e_key.delete(0, "end")
        self.e_val.delete(0, "end")
        self.on_change()
        self._refresh()

    def _delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.on_change()
        self._refresh()

    def _refresh(self) -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        if not self.data:
            ctk.CTkLabel(self.rows, text="(aucune entrée)", text_color=DIM).pack(anchor="w", padx=8, pady=2)
        for key, val in sorted(self.data.items()):
            row = ctk.CTkFrame(self.rows, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=key, width=190, anchor="w", text_color=TEXT).pack(side="left", padx=(4, 8))
            ctk.CTkLabel(row, text=val, anchor="w", text_color=DIM).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="✕", width=28, height=24, fg_color="transparent",
                          hover_color="#4a1522", command=lambda k=key: self._delete(k)).pack(side="right")
