"""Catalogue des commandes affiché dans la page « Commandes ».

Structure : (catégorie, symbole, [(titre, [exemples de phrases], remarque), ...]).
Ces phrases sont des EXEMPLES : Sentinel comprend aussi les formulations proches, et le cerveau IA
comprend les phrases libres (page « Cerveau IA »).
"""
from __future__ import annotations

COMMAND_DOCS: list[tuple[str, str, list[tuple[str, list[str], str]]]] = [
    ("Musique", "♫", [
        ("Jouer un titre", ["mets Life de Damso", "joue Djadja d'Aya Nakamura", "lance Bad Guy de Billie Eilish"],
         "Sur Spotify (lecture directe) si tu l'as connecté dans l'onglet Musique, sinon sur YouTube."),
        ("Jouer un artiste (enchaîne les titres)", ["mets du Damso", "mets de la musique d'Angèle", "mets du rap français"], ""),
        ("Jouer une playlist", ["lance ma playlist rap fr", "lance Life dans la playlist Rap FR"],
         "Enregistre tes playlists dans l'onglet Musique."),
        ("Choisir la source", ["mets Life de Damso sur Spotify", "joue Djadja sur YouTube", "mets du Damso sur YouTube Music"], ""),
        ("Contrôler la lecture", ["pause", "reprends la musique", "musique suivante", "morceau précédent", "passe cette chanson"], ""),
        ("Décrire une ambiance (IA)", ["mets un truc calme pour bosser", "une musique pour faire du sport", "surprends-moi"],
         "Demande le cerveau IA (page Cerveau IA)."),
    ]),
    ("Volume", "◖", [
        ("Régler le volume", ["baisse le son à 40 %", "mets le volume à soixante", "volume à 30", "volume au maximum"], ""),
        ("Monter / baisser", ["monte le son", "baisse le son de 20", "baisse un peu le son", "augmente beaucoup le volume"], ""),
        ("Couper / remettre", ["coupe le son", "remets le son"], ""),
        ("Connaître le volume", ["quel est le volume ?"], ""),
    ]),
    ("Discord", "◈", [
        ("Micro", ["coupe mon micro", "démute-moi", "réactive mon micro", "bascule le micro"],
         "Demande d'avoir réglé les raccourcis (onglet Discord)."),
        ("Casque", ["mets-moi en sourdine", "enlève la sourdine"], ""),
        ("Salon vocal", ["quitte le salon vocal"], ""),
    ]),
    ("Applications et jeux", "▣", [
        ("Lancer n'importe quel programme", ["lance Fortnite", "ouvre Spotify", "joue à Rocket League", "ouvre la calculatrice", "lance le bloc-notes"],
         "Sentinel connaît les programmes de tous tes disques (onglet Applications). Windows garde ses protections habituelles."),
        ("Fermer une application", ["ferme Discord", "quitte Chrome", "ferme Steam"], "Fermeture douce : l'appli peut proposer d'enregistrer."),
        ("Forcer la fermeture", ["tue Fortnite", "force la fermeture de Steam"], ""),
        ("Fenêtre / onglet actifs", ["ferme la fenêtre", "ferme l'onglet", "ferme ce jeu"], ""),
    ]),
    ("Dossiers et fichiers", "▤", [
        ("Dossiers usuels", ["ouvre mes téléchargements", "ouvre mes documents", "ouvre mes images", "ouvre le disque D"], ""),
        ("Un dossier précis", ["ouvre le dossier projets", "ouvre le dossier minecraft"], ""),
        ("Un fichier", ["ouvre le fichier CV", "ouvre le pdf facture EDF", "ouvre la photo vacances"],
         "Recherche par nom dans tes dossiers personnels. Les scripts (.bat, .ps1…) sont refusés."),
    ]),
    ("Fenêtres et bureau", "❐", [
        ("Changer de fenêtre", ["change de fenêtre", "fenêtre suivante"], ""),
        ("Bureau", ["affiche le bureau", "va sur le bureau"], ""),
    ]),
    ("PC", "⏻", [
        ("Veille", ["mets l'ordinateur en veille", "mets le PC en veille"], "Démarre 4 secondes après la réponse."),
        ("Verrouiller", ["verrouille l'ordinateur", "verrouille la session"], ""),
        ("Capture d'écran", ["prends une capture d'écran", "fais un screenshot"], "Enregistrée dans Images\\Sentinel et copiée dans le presse-papiers."),
    ]),
    ("Luminosité de l'écran", "☀", [
        ("Régler", ["mets la luminosité à 50 %", "luminosité au maximum", "luminosité au minimum"], ""),
        ("Monter / baisser", ["baisse la luminosité", "monte la luminosité de vingt"], "Écran de portable direct ; écran externe : module monitorcontrol."),
        ("Connaître", ["quelle est la luminosité ?"], ""),
    ]),
    ("Minuteurs et réveils", "⏱", [
        ("Lancer un minuteur", ["minuteur de 5 minutes", "minuteur d'une heure et demie", "chrono de 30 secondes", "minuteur de 10 minutes pour les pâtes"], ""),
        ("Réveil / rappel", ["réveille-moi dans une heure", "réveille-moi à 7 heures 30", "rappelle-moi de sortir le linge dans 20 minutes"], ""),
        ("Gérer", ["combien de temps il reste ?", "annule le minuteur"], ""),
    ]),
    ("Météo, heure, date", "☂", [
        ("Météo", ["quelle est la météo ?", "météo à Paris", "quelle température il fait ?", "il va pleuvoir demain ?", "météo de demain"],
         "Ville par défaut dans Paramètres → Actions."),
        ("Heure et date", ["quelle heure est-il ?", "quel jour on est ?"], ""),
    ]),
    ("Recherche web", "⌕", [
        ("Chercher", ["cherche des recettes de crêpes", "cherche Interstellar sur YouTube", "recherche prix RTX 4070 sur Google"], ""),
    ]),
    ("Politesses et aide", "☺", [
        ("Discuter un peu", ["bonjour", "merci", "ça va ?", "qui es-tu ?"], ""),
        ("Aide", ["aide", "qu'est-ce que tu sais faire ?"], ""),
        ("Éteindre l'assistant", ["quitte Sentinel"], ""),
    ]),
    ("Discussion et phrases libres (IA)", "✦", [
        ("Poser une question", ["c'est quoi un trou noir ?", "explique-moi la différence entre RAM et SSD", "raconte-moi une blague"],
         "Le cerveau IA répond de tête, sans Internet. Après sa réponse, Sentinel écoute la suite sans mot déclencheur."),
        ("Demander en langage naturel", ["mets un peu moins fort", "il fait quoi comme temps demain à Lille ?", "lance mon jeu de course", "dans dix minutes rappelle-moi la pizza"], ""),
        ("Enchaîner plusieurs actions", ["baisse le son et donne-moi la météo", "ferme Discord puis lance Fortnite"], ""),
    ]),
    ("Tes propres commandes", "⚙", [
        ("Raccourcis vocaux (macros)", ["mode jeu", "bonne nuit"], "À créer plus bas : une phrase → une ou plusieurs commandes."),
    ]),
]
