# SENTINEL — assistant vocal & visuel pour Windows

Assistant en arrière-plan, activé uniquement par le mot **« Sentinel »**, avec une interface HUD façon Jarvis.
Reconnaissance vocale **hors-ligne** (Vosk), voix de réponse Windows (SAPI), **aucune clé d'API**.

## Ce qu'il sait faire

| Domaine | Exemples de phrases |
|---|---|
| Musique | « mets du Damso » · « lance Life dans la playlist Rap FR » · « pause » · « suivant » · « précédent » |
| Volume | « baisse le son à 40 % » · « mets le volume à soixante » · « monte le son de 20 » · « coupe le son » · « quel est le volume ? » |
| Discord | « coupe mon micro » · « démute-moi » · « mets-moi en sourdine » · « quitte le salon vocal » |
| Applis / jeux | « lance Fortnite » · « ouvre la calculatrice » · **« ferme Discord »** · **« tue Chrome »** (fermeture forcée) |
| Fenêtres | **« change de fenêtre »** · **« ferme la fenêtre »** · **« ferme l'onglet »** · **« affiche le bureau »** |
| PC | **« mets l'ordinateur en veille »** · **« verrouille l'ordinateur »** · **« prends une capture d'écran »** |
| Écran | **« mets la luminosité à 50 % »** · **« baisse la luminosité »** · **« quelle est la luminosité ? »** |
| Minuteurs | **« minuteur de 5 minutes »** · **« minuteur de 10 minutes pour les pâtes »** · **« réveille-moi à 7 heures 30 »** · **« combien de temps il reste ? »** · **« annule le minuteur »** |
| Météo | **« quelle est la météo ? »** · **« météo à Paris »** · **« il va pleuvoir demain ? »** |
| Web / divers | « cherche des recettes de crêpes sur YouTube » · « quelle heure est-il ? » · « quel jour on est ? » · « bonjour » · « merci » · « aide » · « quitte Sentinel » |

Dites **« Sentinel »** puis la commande d'une traite, ou **« Sentinel »** seul : il répond et écoute pendant quelques secondes.
La page **Commandes** de l'application reprend cette liste.

## Installation (mode développement)

1. Installer **Python 3.11 ou 3.12** (64 bits) depuis python.org — cocher « Add python.exe to PATH ».
2. Dans le dossier du projet :
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```
3. Au **premier lancement**, l'accueil affiche une carte « Modèle vocal manquant » : cliquer sur *Télécharger* (≈ 41 Mo, une seule fois, stocké dans `%APPDATA%\Sentinel\models`).
4. Choisir son micro dans *Paramètres* si ce n'est pas celui par défaut.

## Nouveautés de la version 3 (voix, IA, Spotify, accès au PC)

### 1. Voix plus naturelle, masculine
Sentinel utilise maintenant une **voix neuronale Microsoft (Henri, masculine)**, gratuite et sans clé. Elle demande
Internet. Sans connexion, il bascule tout seul sur la voix Windows (il préfère une voix française masculine si
elle est installée) puis revient à Henri. Les phrases longues sont lues d'une traite (la suivante est préparée
pendant que la précédente est lue) et les phrases habituelles sont mises en cache : « Oui ? » est instantané.
Réglages : **Paramètres → Voix** (moteur, voix Henri / Rémy / Denise…, hauteur, vitesse).
Installation : `pip install edge-tts` (déjà dans `requirements.txt`).

### 2. Cerveau IA (comprend les phrases libres)
Un modèle de langage **local et gratuit** (Ollama) comprend « mets un truc calme pour bosser », « il pleut demain
à Lille ? », « baisse le son et lance Fortnite », et discute. Rien ne quitte ton PC.
1. Installe Ollama : https://ollama.com/download
2. Dans l'invite de commandes : `ollama pull qwen2.5:7b` (16 Go de RAM) ou `ollama pull qwen2.5:3b` (PC modeste).
3. Onglet **Cerveau IA** → « Actualiser » : l'état passe à « Connecté ».

Fonctionnement : les règles rapides traitent d'abord les commandes simples (instantané). Si Sentinel ne comprend
pas, ou pour une demande vague, la phrase passe au cerveau IA. Mode « Toujours l'IA » disponible.
**Sécurité** : l'IA ne touche jamais au PC. Elle ne peut que proposer des actions d'une liste blanche, dont les
arguments sont vérifiés ; les actions sensibles (veille, verrouillage, fermeture d'application/fenêtre, quitter un
salon Discord) ne partent que si ta phrase les demande clairement. Sans Ollama, tout marche comme avant.

### 3. Spotify : lancer un titre par son nom
Onglet **Musique → Spotify** : crée une appli gratuite sur https://developer.spotify.com/dashboard
(Redirect URI `http://127.0.0.1:8888/callback`, coche « Web API »), colle son Client ID, clique « Connecter ».
Puis : « mets Life de Damso sur Spotify ». **Attention : Spotify impose un compte Premium** pour lancer un titre
depuis une appli externe. Sans Premium, sans connexion ou sans Internet, Sentinel joue le titre sur YouTube.

### 4. Accès à tout le PC
Onglet **Applis & PC** : Sentinel indexe les programmes (.exe) de **tous les disques** (1re analyse : quelques
minutes en tâche de fond, puis cache de 12 h) et tes dossiers/fichiers personnels.
« lance HandBrake » · « ouvre mes téléchargements » · « ouvre le fichier CV » · « ouvre le disque D ».
**Les protections Windows restent intactes** : Sentinel ouvre comme un double-clic. Il ne désactive ni Defender,
ni SmartScreen, ni l'UAC (si un programme demande les droits administrateur, Windows affiche sa fenêtre et c'est
toi qui valides). Il ne supprime, ne déplace ni ne modifie aucun fichier, et refuse d'ouvrir les scripts
(.bat, .ps1, .vbs…) trouvés par la recherche de fichiers.

### 5. Interface et commandes
Nouveau HUD (réacteur entouré de barres audio qui réagissent à ta voix, radar quand l'IA réfléchit, ondes quand
il parle), barre latérale à icônes, cartes à contour fin. La page **Commandes** est maintenant un vrai catalogue
(recherche, bouton ▶ pour essayer une phrase, notes) — et l'IA comprend aussi ce qui n'y figure pas.

### 6. Reconnaissance vocale plus précise (Whisper, facultatif)
Si Sentinel comprend mal, même avec le gros modèle Vosk : `pip install faster-whisper`, puis
**Paramètres → Écoute → Reconnaissance vocale → « Vosk + Whisper »** et Enregistrer. Vosk continue d'écouter en
continu ; dès qu'une phrase s'adresse à Sentinel, Whisper la re-transcrit (bien plus fiable en français) et c'est ce
texte qui devient la commande. Le modèle (« small », ≈ 480 Mo) est téléchargé une fois au premier lancement.
Comptez 1 à 3 secondes de plus par commande, sur le processeur. Si Whisper est absent ou échoue, Vosk prend le relais.
L'accueil affiche l'état de Whisper et le nom du modèle Vosk réellement chargé.

## Nouveautés de la version 4 (intelligence, interaction, apprentissage, thèmes)

### Moins de confusions entre commandes
« Mets Chrome » ouvre maintenant Chrome (et non de la musique) : si un nom correspond nettement à un programme installé,
c'est une application. « Ouvre Google Chrome » n'est plus pris pour une recherche. Sentinel reçoit aussi le texte
original de ta phrase (accents, majuscules), ce qui aide l'IA. Mode « Toujours l'IA » (onglet Cerveau IA) = l'IA
décide de presque tout : plus fin, plus lent.

### Interagir avec les applications
L'IA (et quelques règles) peuvent maintenant : passer à une fenêtre ouverte, taper du texte, utiliser des raccourcis
(nouvel onglet, barre d'adresse, actualiser, copier/coller…), défiler, ouvrir un site, et **cliquer sur un bouton par
son nom** (nécessite `pip install uiautomation`). Exemples : « nouvel onglet », « tape bonjour à tous », « va sur
youtube.com », « clique sur Se connecter », « dans Chrome, ouvre un nouvel onglet et écris météo Lille ».
Garde-fous : rien n'est tapé dans un terminal, le registre ou une console d'administration ; seuls des raccourcis d'une
liste blanche sont possibles (pas d'Alt+F4, de touche Windows, de Suppr) ; les clics refusent tout ce qui est sensible
(supprimer, payer, acheter, désinstaller…) et le bouton doit avoir été nommé par toi ; un plan à plusieurs étapes
s'arrête à la première qui échoue ; Sentinel ne lit pas le contenu de tes fenêtres.

### Un cerveau plus puissant : Claude (option)
Un modèle local reste limité. Onglet **Cerveau IA → Serveur → « Claude — API Anthropic »** : colle une clé API
(console.anthropic.com, paiement à l'usage, distinct d'un abonnement Claude.ai), choisis Haiku (rapide, économique),
Sonnet ou Opus. Attention : tes phrases et la liste de tes applis sont alors envoyées à Anthropic. Mêmes garde-fous.

### Apprendre de ses erreurs
Sur l'accueil, après une commande : **✓ Bien compris** / **✗ Mal compris**. Avec ✗ tu écris ce que tu voulais :
Sentinel retient la correction (elle s'applique ensuite directement à cette phrase ou à une très proche) et la montre
à l'IA comme exemple de ton vocabulaire. ✓ garde comme exemple ce que l'IA avait bien fait. La liste (modifiable) est
dans **Commandes → Ce que Sentinel a appris**. Tout reste local (`%APPDATA%\Sentinel\learned.json`).

### Thèmes, couleurs, HUD
Paramètres → Personnalisation : 7 thèmes (Abysse, Onyx, Nébuleuse, Matrice, Braise, Océan, Crépuscule), couleur de fond
libre, accent (9 couleurs ou code #RRGGBB libre), fond du HUD (dégradé + étoiles, dégradé, uni, minimal), effets
(balayage lumineux, télémétrie CPU/RAM). Le thème et le nom demandent un redémarrage (bouton fourni).

### Donner Sentinel à des amis
Chacun a ses propres réglages (`%APPDATA%\Sentinel`). Au premier lancement, un assistant de bienvenue demande prénom,
mot pour l'appeler, ville, voix (homme/femme) et style. **Paramètres → Profil & partage** exporte / importe un profil
(nom, mot déclencheur, thème, raccourcis, alias, playlists, phrases, voix) sans aucune clé ni identifiant.
Pour eux : soit le dossier + `pip install -r requirements.txt`, soit le `.exe` (voir ci-dessous).

### Lancer depuis le Bureau
- Tout de suite : double-clique **`Creer_raccourci_bureau.bat`** : un raccourci « Sentinel » (avec son icône, sans
  fenêtre noire) apparaît sur le Bureau. Nécessite l'environnement `.venv` déjà installé.
- Vrai `.exe` autonome : double-clique **`build.bat`** (quelques minutes). Il produit `dist\Sentinel.exe` et crée le
  raccourci Bureau. Les fonctions facultatives lourdes (Whisper) alourdissent beaucoup l'exe.

## Version 1.1.6 (en préparation) — permissions, rapidité, mémoire

- **Permissions par famille d'actions** (page dédiée) : fichiers, clavier, clics, sites web, applis,
  fenêtres, veille/verrouillage, Discord — chacune activable/désactivable. Les actions les plus
  sensibles (fermer une appli, veille, verrouillage, quitter Discord) peuvent demander une
  confirmation vocale : Sentinel demande, et n'agit que si tu réponds « oui ».
- **Réponse plus rapide** : en discussion (pas d'action à exécuter), Sentinel commence à parler dès la
  première phrase de l'IA au lieu d'attendre la réponse complète. Jamais avant qu'une action ait fini.
- **Interrompre Sentinel en lui parlant par-dessus** (off par défaut, marche mieux au casque qu'au
  haut-parleur) ; **petit son** de confirmation quand il te reconnaît ; **mode silencieux** (n'agit pas
  moins, mais ne parle plus) ; **Ollama détecté hors ligne** → bouton « Lancer Ollama ».
- **Mémoire à long terme** : « souviens-toi que… » / « retiens que… », consultable dans Commandes.
- **Routines de base** : « bonjour » (heure + météo) et « bonne nuit » (veille), personnalisables comme
  n'importe quelle macro. Pas d'agenda pour l'instant (aucune intégration calendrier).
- **Mémoire réduite** : l'ancienne interface ne construit plus que la page Accueil au démarrage ; les
  huit autres pages ne se fabriquent que si tu les ouvres réellement (avec l'interface web, elle reste
  cachée la plupart du temps). L'analyse de fichiers plafonne plus bas et libère sa mémoire après coup.

## Nouvelle interface web

Sentinel s'ouvre dans une **fenêtre d'application web** (Edge ou Chrome, sans barre d'adresse). Tout est refait :
- **Écran de démarrage** : la sphère de particules qui communiquent, bouton **Démarrer** (la caméra plonge dans la sphère).
- **Accueil** : heure, météo, minuteurs, système, transcription en direct, saisie de commandes, bouton parler, couper
  l'écoute, boutons **✓ Bien compris / ✗ Mal compris** (Sentinel apprend de tes corrections), panneau d'apparence.
- **Conversation** : historique des échanges. **Commandes** : catalogue, testeur de phrases, macros, corrections,
  ce que Sentinel a appris. **Applis et PC**, **Musique** (dont Spotify), **Discord**, **Cerveau IA**, **Voix et écoute**,
  **Réponses**, **Paramètres** (thème, mises à jour, profil à partager, redémarrage) et **Journal** en direct.
- **Assistant de bienvenue** au premier lancement (prénom, mot d'appel, ville, voix, style).
- Tous les réglages s'enregistrent tout seuls ; thèmes et couleurs changent en direct, sans redémarrer.
- `python main.py --classic` (ou `"ui": "classic"`) : ancienne interface. Sans Edge / Chrome, retour automatique à l'ancienne.
- Sécurité : serveur local sur 127.0.0.1 uniquement, jeton secret par session, contrôle de l'en-tête Host et de l'origine,
  aucune ressource externe chargée par la page, chaque réglage vérifié (type, limites, liste blanche) côté Python, et les
  clés secrètes (API) ne sont jamais renvoyées à la page.
- Rendu WebGL avec repli automatique sur un rendu 2D plus léger ; la densité baisse toute seule si l'affichage ralentit.

## Réglages indispensables

### Musique
- **YouTube (défaut)** : Sentinel cherche le titre avec `yt-dlp` et ouvre directement la vidéo dans le navigateur. Pour un artiste seul (« mets du Damso »), il ajoute un mix « radio » qui enchaîne les titres.
- **Playlists** (page *Musique*) : associez un nom parlé à un lien.
  `rap fr` → `https://www.youtube.com/playlist?list=…`
  Avec « lance Life dans la playlist Rap FR », Sentinel cherche « Life » *dans* cette playlist.
- **Spotify** : sans API, Sentinel ne peut qu'ouvrir la recherche / la playlist dans l'appli (`spotify:` URI) — pas de lecture d'un titre précis. Pour de l'instantané et précis, gardez YouTube / YouTube Music.

### Discord
Discord n'expose pas ces actions à l'extérieur : Sentinel **simule des raccourcis clavier globaux** que vous devez d'abord créer dans Discord :
*Paramètres utilisateur → Raccourcis clavier → Ajouter un raccourci* :
- « Activer/désactiver le micro » → `Ctrl+Alt+F9`
- « Activer/désactiver le casque (sourdine) » → `Ctrl+Alt+F10`
- « Quitter le salon vocal » (si votre version le propose) → `Ctrl+Alt+F11`

Les combinaisons sont modifiables dans la page *Discord* de Sentinel (avec un bouton de test).
Limite : Sentinel ne peut pas *lire* l'état réel du micro ; il suppose l'état après chaque bascule (bouton « Resynchroniser l'état du micro » si ça diverge).

### Améliorer la reconnaissance vocale
1. **Installer le gros modèle français** (le plus efficace) : télécharger `vosk-model-fr-0.22.zip` (1,4 Go) sur https://alphacephei.com/vosk/models , l'extraire dans `%APPDATA%\Sentinel\models` (tapez ce chemin dans la barre d'adresse de l'Explorateur), puis relancer Sentinel. Il est choisi automatiquement avant le petit modèle. Prévoir du RAM (plusieurs Go) et un chargement plus long au démarrage.
2. **Regarder le Journal** (page *Journal*, option « afficher tout ce qui est entendu » activée) pour voir ce que Sentinel a réellement compris.
3. **Mot déclencheur** : si « Sentinel » est écrit autrement dans le Journal (« centinelle », « santi nel »…), ajoutez cette forme dans les variantes du mot déclencheur (*Paramètres*).
4. **Noms d'artistes / jeux mal compris** : ajoutez une correction (*Paramètres*, section des corrections).
5. **Phrase habituelle mal comprise ?** Page *Commandes* → *Raccourcis vocaux* : ajoutez la phrase **telle que le Journal la montre**, associée à la commande voulue (ex. `baise le son` → `baisse le son`). Le bouton *Analyser* vous dit ce que Sentinel comprend d'une phrase, sans rien lancer.
6. **Matériel** : choisir le bon micro dans *Paramètres*, régler son niveau d'entrée Windows vers 70-100 %, préférer un casque-micro, et éviter de parler par-dessus de la musique diffusée par les enceintes.

### Nouvelles commandes : ce qu'il faut savoir
- **Fermer une appli** : Sentinel demande poliment à l'application de se fermer (elle peut proposer d'enregistrer). Si elle refuse, dites « tue *nom* » pour forcer. Les processus système (Explorateur, etc.) et Sentinel lui-même sont protégés.
- **Mise en veille** : elle démarre 4 secondes après la réponse. Si l'hibernation est activée dans Windows, c'est elle qui est utilisée (comportement de Windows).
- **Capture d'écran** : enregistrée dans `Images\Sentinel` (dossier modifiable via `screenshot_dir` dans `%APPDATA%\Sentinel\config.json`) **et** copiée dans le presse-papiers (Ctrl+V).
- **Luminosité** : fonctionne directement sur l'écran d'un **portable**. Pour un **écran externe**, installez le module facultatif : `pip install monitorcontrol` (l'écran doit accepter DDC/CI, option à activer dans son menu). Sinon Sentinel répond qu'il ne peut pas régler cet écran.
- **Minuteurs** : plusieurs en parallèle, avec un nom facultatif. À la fin : trois bips puis une phrase. Ils sont perdus si Sentinel est fermé.
- **Météo** : service gratuit Open-Meteo, sans clé. Indiquez votre ville dans *Paramètres → Actions* ; elle s'affiche aussi sur l'accueil.

### Personnaliser ses phrases et ses commandes
- **Page Réponses** : choisissez le style (Jarvis formel, décontracté, court), dites comment Sentinel vous appelle, et remplacez n'importe quelle phrase par la vôtre. Plusieurs variantes ? Séparez-les par `|`.
- **Page Commandes → Raccourcis vocaux** : associez une phrase à une ou plusieurs commandes, séparées par `;`. Exemple : « mode jeu » → `coupe le son ; lance fortnite`.
- **Page Commandes → Tester une phrase** : tapez ce que le Journal montre que Sentinel a entendu ; il indique comment il le comprend (sans rien lancer), ou l'exécute.
- Sentinel répare de lui-même certaines erreurs de reconnaissance (« baise le son » → « baisse le son », un petit mot parasite devant la commande…). Pour le reste, utilisez les raccourcis vocaux ou les corrections.

### Applications & jeux
Sentinel indexe automatiquement Steam, Epic Games, le menu Démarrer et le Bureau, puis compare ce que vous dites aux noms trouvés (approximation floue). Pour un programme introuvable, ajoutez un **alias** dans la page *Applications* (nom parlé → chemin de l'exe, URL ou commande).

### Si un mot est mal compris
En bas de la page *Paramètres* (section des corrections) : `dans so` → `damso`, etc. Le petit modèle français est rapide mais imparfait sur les noms propres : les corrections règlent 90 % des cas.

## Fabriquer le vrai `.exe` avec PyInstaller

### Méthode rapide (recommandée)
Double-cliquez **`build.bat`**. Il crée un environnement virtuel, installe les dépendances, génère l'icône et compile.
Résultat : **`dist\Sentinel.exe`**.

### Méthode manuelle, pas à pas
```bat
:: 1. Dans le dossier du projet, environnement propre
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 2. (Re)générer l'icône si besoin
python tools\make_icon.py

:: 3. Compiler avec la recette fournie
pyinstaller --clean --noconfirm sentinel.spec
```
Le fichier final est `dist\Sentinel.exe`. Vous pouvez le copier n'importe où : la config et le modèle vocal vivent dans `%APPDATA%\Sentinel`, pas à côté de l'exe.

### Équivalent en ligne de commande (sans le .spec)
```bat
pyinstaller --noconfirm --clean --onefile --windowed --name Sentinel ^
  --icon assets\sentinel.ico --add-data "assets;assets" ^
  --collect-all vosk --collect-all sounddevice --collect-all _sounddevice_data ^
  --collect-all customtkinter --collect-all yt_dlp ^
  --hidden-import win32com.client --hidden-import pythoncom ^
  --hidden-import pycaw.pycaw --hidden-import comtypes.stream --hidden-import pystray._win32 ^
  main.py
```
Points clés : `--windowed` = aucune console ; `--add-data "source;destination"` (point-virgule sous Windows) ; `--collect-all` embarque les DLL/fichiers de données que PyInstaller ne détecte pas seul.

### Choix importants
- **`--onefile` (défaut du .spec)** : un seul fichier, mais il se décompresse dans un dossier temporaire à chaque lancement (3 à 8 s de démarrage). Pour un démarrage instantané, mettez `ONEFILE = False` dans `sentinel.spec` : vous obtenez un dossier `dist\Sentinel\` à copier/zipper entier.
- **Le modèle vocal n'est volontairement PAS embarqué** dans l'exe : il est téléchargé au premier lancement dans `%APPDATA%\Sentinel\models`. Vous pouvez aussi le déposer à la main : dossier `models\vosk-model-small-fr-0.22` à côté de l'exe.
- **Ne pas activer UPX** : il multiplie les faux positifs antivirus.

### Problèmes fréquents
| Symptôme | Cause / solution |
|---|---|
| L'exe se ferme aussitôt | Ouvrir `%APPDATA%\Sentinel\sentinel.log` : l'erreur y est écrite. Pour voir la console pendant le débogage, mettre `console=True` dans le .spec. |
| `ModuleNotFoundError` au lancement de l'exe | Ajouter le module dans `hiddenimports` du .spec, recompiler. |
| Windows Defender / antivirus bloque l'exe | Faux positif courant pour un exe PyInstaller qui simule des touches (SendInput). Ajouter une exclusion pour `dist\` ou signer l'exe. |
| « Sentinel est déjà en cours d'exécution » | Il tourne déjà dans la zone de notification (près de l'horloge). |
| La musique ne se lance plus | YouTube change régulièrement : `pip install -U yt-dlp` puis **recompiler** l'exe. |
| Pas de son de réponse | Vérifier qu'une voix française est installée (Paramètres Windows → Heure et langue → Voix) et choisir la voix dans *Paramètres*. |

### Lancement automatique avec Windows
L'interrupteur *Paramètres → Lancer Sentinel au démarrage de Windows* ajoute une entrée dans `HKCU\...\Run` avec l'option `--minimized` : Sentinel démarre réduit dans la zone de notification.

## Structure du projet
```
main.py                  point d'entrée (instance unique, logs, fenêtre)
sentinel.spec            recette PyInstaller
build.bat                compilation en un clic
requirements.txt
assets/sentinel.ico      icône
tools/make_icon.py       génère l'icône
sentinel/
  config.py              réglages JSON (%APPDATA%\Sentinel\config.json)
  nlu.py                 compréhension du français (phrases -> intentions)
  voice.py               micro + Vosk + mot déclencheur + voix SAPI
  assistant.py           chef d'orchestre
  system.py              instance unique, démarrage Windows
  replies.py             toutes les phrases prononcées (3 styles + personnalisation)
  actions/               music, discord, keyboard, system_audio, apps, web, pc, timers, weather
  ui/                    app (fenêtre), hud (réacteur animé), command_docs, tray, widgets, theme
  tts.py                 voix neuronale (Edge) + repli Windows
  asr.py                 Whisper (reconnaissance de précision, facultatif)
  learning.py            mémoire d'apprentissage (corrections de l'utilisateur)
  actions/interact.py    fenêtres, clavier, clics, sites (avec garde-fous)
  webui/                 nouvelle interface web : server.py (API locale sécurisée), controller.py, schema.py (réglages vérifiés), window.py, static/ (HTML, CSS, JS, WebGL)
  permissions.py         familles d'actions et confirmation vocale
  facts.py               mémoire à long terme (« souviens-toi que… »)
  say_stream.py           extraction progressive de la réponse de l'IA en flux
  beep.py                 son de réveil
  brain.py               cerveau IA local (Ollama), actions autorisées et garde-fous
  actions/scan.py        analyse des .exe, dossiers et fichiers
  actions/spotify.py     lecture directe Spotify (API officielle, PKCE)
```

## Personnalisation
- **Mot déclencheur** : *Paramètres* (mot + variantes phonétiques acceptées).
- **Couleur du HUD** : Cyan, Orange, Rouge, Vert, Violet.
- **Nouvelles commandes** : ajouter une règle dans `sentinel/nlu.py` (`_parse`), un `case` dans `Assistant._execute`, et si besoin une phrase dans `sentinel/replies.py`.
