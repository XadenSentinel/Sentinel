# Publier Sentinel sur GitHub et sortir une mise à jour

## Une seule fois : créer le dépôt et y mettre le code
1. github.com → **New repository** : nom `sentinel`, **Public**, ne coche rien d'autre (pas de README, pas de licence pour l'instant).
2. Installe **Git for Windows** (git-scm.com), puis dans l'invite de commandes, DANS le dossier du projet :
   ```
   git init
   git add .
   git commit -m "Sentinel 1.1.5"
   git branch -M main
   git remote add origin https://github.com/TON_PSEUDO/sentinel.git
   git push -u origin main
   ```
   (une fenêtre du navigateur s'ouvre pour te connecter à GitHub la première fois)
3. (Déjà fait pour `XadenSentinel/Sentinel` : la ligne `UPDATE_REPO` de `sentinel/__init__.py` est remplie.)
4. Sur GitHub : **Settings → Password and authentication** : active la double authentification (2FA). Qui contrôle ton compte contrôle les mises à jour de tous tes utilisateurs.

## À chaque nouvelle version
1. Change le numéro dans `sentinel/__init__.py` (ex. `__version__ = "1.1.6"`).
2. ```
   git add .
   git commit -m "Version 1.1.6 : ce qui change"
   git push
   git tag v1.1.6
   git push origin v1.1.6
   ```
3. GitHub (onglet **Actions**) compile `Sentinel.exe` sur Windows, calcule son empreinte SHA-256 et crée la **Release** avec les deux fichiers (compte 5 à 10 minutes).
4. Dans Sentinel : Paramètres → Mises à jour → **Rechercher une mise à jour** → **Mettre à jour et redémarrer**.

Règles : le tag doit être `v` + le numéro du code (sinon la compilation s'arrête volontairement) ; ne modifie jamais une Release déjà publiée, sors plutôt une version suivante.

## Si la compilation échoue
Onglet **Actions** → clique sur l'exécution en rouge → copie le message d'erreur et envoie-le moi.
