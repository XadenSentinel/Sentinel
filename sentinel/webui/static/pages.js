(function () {
  'use strict';
  const core = window.core;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const api = core.api, action = (n, d) => core.action(n, d), toast = (t) => core.toast(t);
  let current = null, cleanups = [];

  // ------------------------------------------------------------------ enregistrement d'un réglage
  const timers = {};
  function save(key, value, row, indicator) {
    return api('setting', { key, value }).then((r) => {
      const old = row.querySelector('.f-err'); if (old) old.remove();
      if (!r.ok) { const e = el('div', 'f-err', r.error || 'Valeur refusée'); row.append(e); return r; }
      if (indicator) { indicator.classList.add('on'); clearTimeout(indicator._t); indicator._t = setTimeout(() => indicator.classList.remove('on'), 1400); }
      if (r.snapshot) core.applySnapshot(r.snapshot);
      return r;
    }).catch(() => toast('Sentinel ne répond pas.'));
  }
  const debounced = (key, fn, ms) => { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); };

  // ------------------------------------------------------------------ contrôles
  function dictEditor(f, ctl, row, ind) {
    const rows = el('div', 'dict-rows'), pairs = Object.entries(f.value || {});
    const commit = () => {
      const obj = {}; pairs.forEach(([k, v]) => { if (k.trim()) obj[k.trim()] = v; });
      debounced(f.key, () => save(f.key, obj, row, ind), 500);
    };
    const render = () => {
      rows.innerHTML = '';
      pairs.forEach((p, i) => {
        const r = el('div', 'dict-row'), k = el('input'), v = el('input'), x = el('button', 'x', '✕');
        k.type = v.type = 'text'; k.value = p[0]; v.value = p[1]; k.placeholder = f.kph || ''; v.placeholder = f.vph || '';
        k.addEventListener('input', () => { p[0] = k.value; commit(); }); v.addEventListener('input', () => { p[1] = v.value; commit(); });
        x.type = 'button'; x.title = 'Supprimer'; x.addEventListener('click', () => { pairs.splice(i, 1); render(); commit(); });
        r.append(k, v, x); rows.append(r);
      });
      const add = el('button', 'btn', '+ Ajouter'); add.type = 'button';
      add.addEventListener('click', () => { pairs.push(['', '']); render(); const ins = rows.querySelectorAll('.dict-row:last-of-type input'); if (ins[0]) ins[0].focus(); });
      rows.append(el('div', 'btnrow')); rows.lastChild.append(add);
    };
    render(); ctl.append(rows);
  }

  function makeField(f, ind) {
    const row = el('div', 'field' + (f.type === 'dict' ? ' wide' : ''));
    if (f.type !== 'dict') {
      const left = el('div', 'f-l'); left.append(el('div', 'f-label', f.label));
      if (f.help) left.append(el('div', 'f-help small dim', f.help));
      row.append(left);
    }
    const ctl = el('div', 'f-c'); row.append(ctl);
    const v = f.value, key = f.key;
    if (f.type === 'bool') {
      const lab = el('label', 'switch'), inp = el('input'), sp = el('span');
      inp.type = 'checkbox'; inp.checked = !!v; lab.append(inp, sp); ctl.append(lab);
      inp.addEventListener('change', () => save(key, inp.checked, row, ind));
    } else if (f.type === 'text' || f.type === 'secret' || f.type === 'list') {
      const inp = el('input'); inp.type = f.type === 'secret' ? 'password' : 'text'; inp.placeholder = f.ph || '';
      if (f.type === 'list') inp.value = (v || []).join(', ');
      else if (f.type === 'secret') { inp.placeholder = v && v.set ? 'Clé enregistrée ••••••••' : (f.ph || ''); }
      else inp.value = v == null ? '' : v;
      const commit = () => { if (f.type === 'secret' && !inp.value.trim()) return; save(key, inp.value, row, ind).then(() => { if (f.type === 'secret') { inp.value = ''; inp.placeholder = 'Clé enregistrée ••••••••'; } }); };
      inp.addEventListener('change', commit); inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(); });
      ctl.append(inp);
      if (f.type === 'secret') { const c = el('button', 'btn', 'Effacer'); c.type = 'button'; c.addEventListener('click', () => action('secret_clear', { key }).then(() => { inp.placeholder = f.ph || ''; toast('Clé effacée'); })); ctl.append(c); }
      if (f.test) {
        const t = el('button', 'btn', 'Tester'); t.type = 'button';
        t.addEventListener('click', () => save(key, inp.value, row, ind).then(() => action('discord_test', { action: f.test })).then((r) => {
          let note = row.querySelector('.f-note'); if (!note) { note = el('div', 'f-note'); row.append(note); }
          note.textContent = r && r.ok ? '→ ' + r.text : '→ ' + ((r && r.error) || 'échec');
        }));
        ctl.append(t);
      }
    } else if (f.type === 'int') {
      const box = el('div', 'range'), inp = el('input'), out = el('b');
      inp.type = 'range'; inp.min = f.min; inp.max = f.max; inp.step = f.step || 1; inp.value = v;
      const show = () => { out.textContent = inp.value + (f.unit || ''); }; show();
      inp.addEventListener('input', show); inp.addEventListener('change', () => save(key, +inp.value, row, ind));
      box.append(inp, out); ctl.append(box);
    } else if (f.type === 'select') {
      const sel = el('select');
      (f.options || []).forEach(([val, lab]) => { const o = el('option', '', lab); o.value = val; sel.append(o); });
      sel.value = v == null ? '' : v; if (sel.value !== String(v == null ? '' : v) && sel.options.length) sel.selectedIndex = 0;
      sel.addEventListener('change', () => save(key, sel.value, row, ind)); ctl.append(sel);
    } else if (f.type === 'color') {
      const pick = el('input', 'colorin'), txt = el('input'), clr = el('button', 'btn', 'Aucune');
      pick.type = 'color'; pick.value = v || '#00e5ff'; txt.type = 'text'; txt.placeholder = '#RRGGBB'; txt.value = v || ''; txt.style.maxWidth = '120px'; clr.type = 'button';
      pick.addEventListener('input', () => { txt.value = pick.value; debounced(key, () => save(key, pick.value, row, ind), 350); });
      txt.addEventListener('change', () => { if (/^#[0-9a-f]{6}$/i.test(txt.value)) pick.value = txt.value; save(key, txt.value, row, ind); });
      clr.addEventListener('click', () => { txt.value = ''; save(key, '', row, ind); });
      ctl.append(pick, txt, clr);
    } else if (f.type === 'dict') {
      dictEditor(f, ctl, row, ind);
    }
    return row;
  }

  function sectionCard(sec, extra) {
    const card = el('div', 'pcard'), h = el('div', 'card-h'), ind = el('span', 'saved', 'Enregistré ✓');
    h.append(el('span', '', sec.title), ind); card.append(h);
    if (sec.help) card.append(el('p', 'chelp', sec.help));
    if (extra && extra.before) extra.before(card);
    sec.fields.forEach((f) => card.append(makeField(f, ind)));
    if (extra && extra.after) extra.after(card);
    return card;
  }
  const btn = (label, fn, cls) => { const b = el('button', 'btn' + (cls ? ' ' + cls : ''), label); b.type = 'button'; b.addEventListener('click', fn); return b; };
  const listen = (t, fn) => { core.on(t, fn); cleanups.push(() => core.off(t, fn)); };
  const dot = (cls) => el('span', 'dot ' + (cls || ''));

  // ------------------------------------------------------------------ blocs spécifiques
  function blockApps(root) {
    const card = el('div', 'pcard'); card.append(el('div', 'card-h', 'État de l\'analyse'));
    const kv = el('div', 'kvs'), a = el('b', '', '—'), f = el('b', '', '—');
    const s1 = el('span', '', 'Applications et programmes'), s2 = el('span', '', 'Fichiers et dossiers');
    s1.append(a); s2.append(f); kv.append(s1, s2); card.append(kv);
    api('data?name=system').then((d) => { a.textContent = (d.apps || 0).toLocaleString('fr-FR'); f.textContent = (d.files || 0).toLocaleString('fr-FR'); });
    listen('apps_indexed', (n) => { a.textContent = Number(n).toLocaleString('fr-FR'); });
    listen('files_indexed', (n) => { f.textContent = Number(n).toLocaleString('fr-FR'); });
    const row = el('div', 'btnrow'); row.append(btn('Réanalyser maintenant', () => action('apps_rescan').then(() => toast('Analyse relancée en tâche de fond')), 'primary'));
    row.append(el('span', 'small dim', '1re analyse : quelques minutes ; ensuite mise en cache 12 h.')); card.append(row);
    root.append(card);
  }

  function blockCommands(root) {
    const holder = el('div'); root.append(holder);                 // réserve la place : l'ordre ne dépend pas du réseau
    api('data?name=commands').then((d) => {
      const card = el('div', 'pcard'); card.append(el('div', 'card-h', 'Tester une phrase'));
      card.append(el('p', 'chelp', 'Dis « ' + d.wake + ' » puis une de ces phrases. Les formulations proches marchent aussi, et le cerveau IA comprend les phrases libres.'));
      const box = el('div', 'testbox'), inp = el('input'), res = el('div', 'result');
      inp.type = 'text'; inp.placeholder = 'Tape une phrase pour voir comment Sentinel la comprend…';
      const analyse = () => { const t = inp.value.trim(); if (t) action('explain', { text: t }).then((r) => { res.textContent = '→ ' + (r.text || r.error || ''); }); };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') analyse(); });
      box.append(inp, btn('Analyser', analyse), btn('Exécuter', () => { const t = inp.value.trim(); if (t) { action('command', { text: t }); res.textContent = '→ exécution…'; } }, 'primary'));
      card.append(box, res);
      const search = el('input'); search.type = 'text'; search.placeholder = 'Rechercher une commande (ex. minuteur, volume, fichier, spotify…)'; search.style.width = '100%'; search.style.marginBottom = '14px'; card.append(search);
      holder.append(card);
      const list = el('div'); holder.append(list);
      const norm = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      const draw = () => {
        list.innerHTML = ''; const q = norm(search.value);
        d.docs.forEach((cat) => {
          const entries = cat.entries.filter((e) => !q || norm([cat.category, e.title, e.note].concat(e.examples).join(' ')).includes(q));
          if (!entries.length) return;
          const c = el('div', 'pcard'); c.append(el('div', 'card-h', cat.icon + '  ' + cat.category));
          entries.forEach((e) => {
            const en = el('div', 'entry'); en.append(el('b', '', e.title));
            const chips = el('div', 'chips');
            e.examples.forEach((ex) => { const ch = el('button', 'chip', '« ' + ex + ' »'); ch.type = 'button'; ch.addEventListener('click', () => { inp.value = ex; analyse(); window.scrollTo(0, 0); $('page').scrollTop = 0; }); chips.append(ch); });
            en.append(chips); if (e.note) en.append(el('div', 'small dim', e.note)); c.append(en);
          });
          list.append(c);
        });
        if (!list.children.length) list.append(el('p', 'chelp', 'Aucune commande ne correspond. Dis-le en langage naturel : le cerveau IA comprend.'));
      };
      search.addEventListener('input', draw); draw();
    });
  }

  function blockLearned(root) {
    const card = el('div', 'pcard'), h = el('div', 'card-h'); h.append(el('span', '', '✦  Ce que Sentinel a appris de toi'));
    const clr = btn('Tout oublier', () => action('learned_clear'), 'danger'); h.append(clr); card.append(h);
    card.append(el('p', 'chelp', 'Quand tu cliques sur « ✗ Mal compris » sur l\'accueil et que tu dis ce que tu voulais, Sentinel le retient : la prochaine fois il applique ta correction et s\'en sert pour comprendre les phrases voisines.'));
    const list = el('div'); card.append(list); root.append(card);
    const load = () => api('data?name=learned').then((d) => {
      list.innerHTML = '';
      if (!d.items.length) { list.append(el('p', 'small dim', 'Rien pour l\'instant.')); return; }
      d.items.forEach((i) => {
        const r = el('div', 'learned-row'); r.append(el('span', '', '« ' + i.heard + ' »  →  ' + (i.kind === 'fix' ? '« ' + i.meant + ' »' : '(exemple validé : l\'IA avait bien compris)')));
        const x = el('button', 'x', '✕'); x.type = 'button'; x.style.width = '34px'; x.addEventListener('click', () => action('learned_remove', { ts: i.ts })); r.append(x); list.append(r);
      });
    });
    load(); listen('learned', load);
  }

  function blockSpotify(card) {
    card.append(el('p', 'chelp', 'Pour que « mets Life de Damso » lance vraiment le titre dans Spotify :\n1. developer.spotify.com/dashboard → « Create app » (nom libre).\n2. Redirect URI : http://127.0.0.1:8888/callback · coche « Web API » puis enregistre.\n3. Copie le Client ID, colle-le ci-dessous puis clique sur « Connecter Spotify ».\nSpotify impose un compte Premium pour la commande à distance. Sans Premium ou sans connexion, Sentinel joue le titre sur YouTube à la place.'));
    const row = el('div', 'btnrow'), st = el('span', 'small dim', '…');
    row.append(btn('Connecter Spotify', () => { st.textContent = 'Autorise Sentinel dans ton navigateur…'; action('spotify_connect').then((r) => { if (r && r.ok === false) st.textContent = r.error; }); }, 'primary'), btn('Déconnecter', () => action('spotify_disconnect')), st);
    card.append(row);
    const refresh = () => api('data?name=spotify').then((d) => { st.textContent = d.connected ? 'Connecté ✓' : 'Non connecté'; st.style.color = d.connected ? 'var(--ok)' : ''; });
    refresh(); listen('spotify_status', (msg) => { toast('Spotify : ' + msg); refresh(); });
  }

  function blockDiscord(card) {
    card.append(el('p', 'chelp', 'Sentinel appuie sur des raccourcis clavier GLOBAUX que tu déclares dans Discord :\nDiscord → Paramètres utilisateur → Raccourcis clavier → Ajouter → choisis l\'action, clique sur « Enregistrer le raccourci » et tape la même combinaison que ci-dessous.\nActions à lier : « Activer/désactiver le micro » (Toggle Mute), « Activer/désactiver le casque » (Toggle Deafen) et une action pour quitter le salon vocal si ta version la propose.\nSi Discord tourne en administrateur, Sentinel doit l\'être aussi, sinon Windows bloque les touches simulées.'));
    const row = el('div', 'btnrow'); row.append(btn('Resynchroniser l\'état du micro', () => action('discord_reset').then(() => toast('État resynchronisé')))); card.append(row);
  }

  function blockBrain(root) {
    const card = el('div', 'pcard'); card.append(el('div', 'card-h', 'État'));
    const line = el('div', 'status-line'), d = dot('wait'), txt = el('span', '', 'Vérification…'); line.append(d, txt); card.append(line);
    const launch = btn('Lancer Ollama', () => { launch.disabled = true; launch.textContent = 'Lancement…'; action('ollama_launch').then((r) => { if (r && r.ok === false) { toast(r.error); launch.disabled = false; launch.textContent = 'Lancer Ollama'; } else { setTimeout(() => { launch.disabled = false; launch.textContent = 'Lancer Ollama'; }, 4000); } }); }, 'primary');
    launch.style.display = 'none'; line.append(launch);
    const set = (st, canLaunch) => {
      if (!st) return; d.className = 'dot ' + (st.ok ? 'ok' : 'bad'); txt.textContent = st.message || (st.ok ? 'Connecté' : 'Hors ligne');
      launch.style.display = canLaunch ? '' : 'none';
    };
    api('data?name=brain').then((r) => set(r.status, r.can_launch));
    listen('brain', (st) => api('data?name=brain').then((r) => set(st, r.can_launch)));
    card.append(el('p', 'chelp', 'Avec le cerveau IA, Sentinel comprend les phrases libres (« mets un truc calme pour bosser », « il pleut demain ? », « baisse le son et lance Fortnite ») et sait discuter. Le modèle local tourne sur ton PC via Ollama : gratuit, privé. Sans lui, toutes les commandes classiques marchent.'));
    const row = el('div', 'btnrow'); row.append(btn('Vérifier la connexion', () => { d.className = 'dot wait'; txt.textContent = 'Vérification…'; action('brain_check'); }, 'primary'), btn('Effacer sa mémoire', () => action('brain_forget').then(() => toast('Mémoire effacée')))); card.append(row);
    const det = (title, text) => { const x = el('details'), s = el('summary', '', title); x.append(s, el('p', 'chelp', text)); return x; };
    card.append(det('Installer l\'IA locale (gratuit, environ 5 minutes)', '1. Télécharge et installe Ollama : ollama.com/download (Windows). Il se lance tout seul en arrière-plan.\n2. Ouvre l\'invite de commandes et télécharge un modèle :\n   16 Go de RAM ou carte graphique récente :  ollama pull qwen2.5:7b\n   PC plus modeste (8 Go de RAM) :  ollama pull qwen2.5:3b\n3. Reviens ici et clique sur « Vérifier la connexion ».\nSécurité : l\'IA ne touche jamais au PC directement. Elle ne peut que choisir parmi les actions prévues, et les actions sensibles (veille, verrouillage, fermeture…) ne partent que si tu les as clairement demandées.'));
    card.append(det('Option : Claude (beaucoup plus intelligent)', 'Choisis « Claude — API Anthropic » dans Serveur, colle ta clé API, choisis un modèle (Haiku : rapide et économique · Sonnet : plus fin · Opus : le plus puissant).\nLa clé se crée sur console.anthropic.com (compte API avec du crédit : distinct d\'un abonnement Claude.ai). Tu paies à l\'usage ; vérifie les tarifs sur le site d\'Anthropic.\nConfidentialité : avec Claude, tes phrases et la liste de tes applications sont envoyées à Anthropic. La clé est enregistrée en clair dans %APPDATA%\\Sentinel : ne partage pas ce dossier.\nLes mêmes garde-fous s\'appliquent : Claude ne peut lancer que les actions autorisées.'));
    root.append(card);
  }

  function blockVoiceTest(card) {
    const row = el('div', 'btnrow'); row.append(btn('Tester la voix', () => action('voice_test'), 'primary')); card.append(row);
  }
  function blockWhisper(card) {
    const line = el('div', 'status-line'), d = dot(), txt = el('span', 'small dim', 'Whisper : désactivé'); line.append(d, txt); card.append(line);
    listen('asr', (state, detail) => {
      const map = { off: ['', 'Whisper : désactivé'], loading: ['wait', 'Whisper : chargement ' + detail + '… (1re fois : téléchargement)'], ready: ['ok', 'Whisper : prêt ✓ (' + detail + ')'], error: ['bad', 'Whisper indisponible — ' + detail] };
      const m = map[state] || ['', state]; d.className = 'dot ' + m[0]; txt.textContent = m[1];
    });
  }

  function blockReplies(root) {
    api('data?name=replies').then((d) => {
      const card = el('div', 'pcard'); card.append(el('div', 'card-h', 'Mes propres phrases'));
      card.append(el('p', 'chelp', 'Laisse un champ vide pour garder la phrase du style choisi (en grisé). Plusieurs variantes ? Sépare-les par « | » : Sentinel en choisit une au hasard. Les mots entre accolades, comme {p}, sont remplacés automatiquement ; {appel} ajoute ton prénom. Le bouton ▶ prononce la phrase.'));
      d.items.forEach((it) => {
        const row = el('div', 'field'), left = el('div', 'f-l'), ctl = el('div', 'f-c');
        left.append(el('div', 'f-label', it.label)); if (it.args.length) left.append(el('div', 'f-help small dim', it.args.map((a) => '{' + a + '}').join(' ')));
        const inp = el('input'); inp.type = 'text'; inp.placeholder = it.default; inp.value = it.custom || '';
        inp.addEventListener('change', () => action('reply_set', { key: it.key, text: inp.value }));
        const play = btn('▶', () => action('reply_preview', { key: it.key, text: inp.value })); play.style.width = '40px'; play.style.padding = '0'; play.title = 'Écouter';
        ctl.append(inp, play); row.append(left, ctl); card.append(row);
      });
      const r = el('div', 'btnrow'); r.append(btn('Tout réinitialiser', () => action('reply_reset').then(() => { toast('Phrases réinitialisées'); openPage('replies'); }), 'danger')); card.append(r);
      root.append(card);
    });
  }

  function blockUpdate(card) {
    const line = el('div', 'status-line'), txt = el('span', '', 'Version installée : …'), notes = el('p', 'chelp'), bar = el('div', 'progress'), fill = el('i'); bar.append(fill); bar.style.display = 'none';
    line.append(txt); card.append(line, notes, bar);
    const install = btn('Mettre à jour et redémarrer', () => { install.disabled = true; txt.textContent = 'Téléchargement…'; action('update_install'); }, 'primary'); install.disabled = true;
    const back = btn('Version précédente', () => action('update_rollback').then((r) => { if (r && r.ok === false) txt.textContent = r.error; }));
    const row = el('div', 'btnrow'); row.append(btn('Rechercher une mise à jour', () => { txt.textContent = 'Recherche en cours…'; action('update_check'); }), install, back); card.append(row);
    api('data?name=update').then((d) => {
      txt.textContent = 'Version installée : ' + d.version + (d.enabled ? '' : ' — mises à jour non configurées');
      if (d.available) { txt.textContent += ' · version ' + d.available + ' disponible'; install.disabled = false; }
      back.style.display = d.previous ? '' : 'none';
    });
    listen('update', (state, p) => {
      if (state === 'available' && p) { txt.textContent = 'Nouvelle version disponible : ' + p.version; notes.textContent = (p.notes || '').slice(0, 600); install.disabled = false; }
      else if (state === 'uptodate') { txt.textContent = 'Tu es à jour ✓'; notes.textContent = ''; }
      else if (state === 'progress') { bar.style.display = ''; fill.style.width = (p && p[1] ? Math.round(100 * p[0] / p[1]) : 50) + '%'; }
      else if (state === 'installed') { txt.textContent = 'Installation en cours : Sentinel va se fermer puis se relancer tout seul…'; }
      else if (state === 'error') { txt.textContent = String(p); install.disabled = false; }
    });
    card.append(el('p', 'chelp', 'Rien ne s\'installe sans ton clic. Tes réglages, ce que Sentinel a appris et tes connexions sont conservés ; l\'ancienne version est gardée pour pouvoir revenir en arrière.'));
  }

  function blockProfile(root) {
    const card = el('div', 'pcard'); card.append(el('div', 'card-h', 'Profil et partage (pour tes amis)'));
    card.append(el('p', 'chelp', 'Exporte tes réglages (nom, mot déclencheur, thème, raccourcis vocaux, alias, playlists, phrases, voix…) dans un fichier à envoyer à un ami : il l\'importe et retrouve ta configuration. Aucune clé ni identifiant n\'y figure.'));
    const row = el('div', 'btnrow'), file = el('input'), msg = el('span', 'small dim'); file.type = 'file'; file.accept = '.json'; file.style.display = 'none';
    row.append(btn('Exporter mon profil…', () => action('profile_export').then((r) => {
      const a = el('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(r.profile, null, 2)], { type: 'application/json' })); a.download = 'mon-profil-sentinel.json'; a.click(); msg.textContent = 'Profil exporté ✓';
    })), btn('Importer un profil…', () => file.click()), file, msg); card.append(row);
    file.addEventListener('change', () => {
      const f = file.files[0]; if (!f) return;
      f.text().then((t) => { let j; try { j = JSON.parse(t); } catch (e) { msg.textContent = 'Fichier invalide'; return; }
        action('profile_import', { settings: (j && j.settings) || {} }).then((r) => { msg.textContent = (r.count || 0) + ' réglages importés ✓'; if (r.snapshot) core.applySnapshot(r.snapshot); }); });
    });
    root.append(card);
    const c2 = el('div', 'pcard'); c2.append(el('div', 'card-h', 'Sentinel'));
    const r2 = el('div', 'btnrow'); r2.append(btn('Redémarrer Sentinel', () => { toast('Redémarrage…'); action('restart'); }), btn('Ouvrir l\'ancienne interface', () => action('open_classic', { page: '' }))); c2.append(r2); root.append(c2);
  }

  // ------------------------------------------------------------------ journal
  function pageLog(root) {
    const card = el('div', 'pcard'), h = el('div', 'card-h'); h.append(el('span', '', 'Journal en direct'));
    const filters = el('div', 'filters'); let filter = 'all';
    [['all', 'Tout'], ['cmd', 'Commandes'], ['reply', 'Réponses'], ['heard', 'Entendu'], ['info', 'Infos'], ['error', 'Erreurs']].forEach(([k, l]) => {
      const b = el('button', 'mini' + (k === 'all' ? ' on' : ''), l); b.type = 'button';
      b.addEventListener('click', () => { filter = k; filters.querySelectorAll('.mini').forEach((x) => x.classList.toggle('on', x === b)); draw(); }); filters.append(b);
    });
    h.append(filters); card.append(h);
    const box = el('div', 'logbox'); card.append(box);
    const r = el('div', 'btnrow'); r.append(btn('Effacer', () => action('log_clear').then(() => { items.length = 0; draw(); }), 'danger')); card.append(r); root.append(card);
    const items = [], label = { heard: 'entendu', cmd: 'COMMANDE', reply: 'réponse', info: 'info', error: 'ERREUR' };
    const line = (i) => { const l = el('div', 'logline lk-' + i.kind); l.append(el('span', 'k', i.ts), el('span', 'k', label[i.kind] || i.kind), el('span', 'm', i.text)); return l; };
    const draw = () => { box.innerHTML = ''; items.filter((i) => filter === 'all' || i.kind === filter).forEach((i) => box.append(line(i))); box.scrollTop = box.scrollHeight; };
    api('data?name=log').then((d) => { d.items.forEach((i) => items.push(i)); draw(); });
    listen('log', (kind, text) => {
      const i = { ts: new Date().toLocaleTimeString('fr-FR'), kind, text: String(text) }; items.push(i); if (items.length > 500) items.shift();
      if (filter === 'all' || filter === kind) { box.append(line(i)); box.scrollTop = box.scrollHeight; }
    });
  }

  // ------------------------------------------------------------------ assemblage des pages
  const TITLES = { commands: 'Commandes', apps: 'Applis et PC', music: 'Musique', discord: 'Discord', brain: 'Cerveau IA', voice: 'Voix et écoute', replies: 'Réponses', settings: 'Paramètres', log: 'Journal' };
  const SUBS = {
    commands: 'La liste de ce que Sentinel comprend, un testeur de phrases, et tes propres raccourcis.',
    apps: 'Sentinel connaît les programmes, dossiers et fichiers de ton PC. Il les ouvre comme un double-clic : rien n\'est désactivé dans Windows.',
    music: 'Choisis d\'où vient la musique, connecte Spotify pour lancer un titre par son nom, et enregistre tes playlists.',
    discord: 'Contrôle ton micro et ta sourdine Discord à la voix.',
    voice: 'La voix de Sentinel et la façon dont il t\'écoute.',
    replies: 'Le ton de Sentinel et tes propres phrases de réponse.',
    permissions: 'Active ou coupe des familles entières d\'actions, et choisis lesquelles demandent une confirmation vocale.',
  };
  const EXTRAS = {
    music: { 'Spotify — lecture directe': { after: blockSpotify } },
    discord: { 'Raccourcis clavier': { after: blockDiscord } },
    voice: { 'Voix de Sentinel': { after: blockVoiceTest }, 'Écoute': { after: blockWhisper } },
    settings: { 'Mises à jour': { before: blockUpdate } },
  };
  function blockFacts(root) {
    const card = el('div', 'pcard'), h = el('div', 'card-h'); h.append(el('span', '', '🧠  Ce que Sentinel sait de toi'));
    const clr = btn('Tout oublier', () => action('fact_clear'), 'danger'); h.append(clr); card.append(h);
    card.append(el('p', 'chelp', 'Dis « souviens-toi que… » ou « retiens que… » pour lui apprendre quelque chose sur toi. Il s\'en sert dans ses réponses avec le cerveau IA (« mon chat s\'appelle Nuage », « je travaille de nuit »…).'));
    const list = el('div'); card.append(list); root.append(card);
    const load = () => api('data?name=facts').then((d) => {
      list.innerHTML = '';
      if (!d.items.length) { list.append(el('p', 'small dim', 'Rien pour l\'instant.')); return; }
      d.items.forEach((i) => {
        const r = el('div', 'learned-row'); r.append(el('span', '', '« ' + i.text + ' »'));
        const x = el('button', 'x', '✕'); x.type = 'button'; x.style.width = '34px'; x.addEventListener('click', () => action('fact_remove', { ts: i.ts }).then(load)); r.append(x); list.append(r);
      });
    });
    load();
  }

  const TOP = { apps: blockApps, commands: (r) => { blockCommands(r); blockLearned(r); blockFacts(r); }, brain: blockBrain };
  const BOTTOM = { replies: blockReplies, settings: blockProfile };

  async function openPage(name) {
    current = name; cleanups.forEach((f) => f()); cleanups = [];
    const root = $('page'); root.innerHTML = '';
    const head = el('div', 'page-h'); head.append(el('h2', 'title', TITLES[name] || name)); root.append(head);
    if (SUBS[name]) root.append(el('p', 'page-sub', SUBS[name]));
    if (name === 'log') { pageLog(root); return; }
    if (TOP[name]) TOP[name](root);
    let sc;
    try { sc = await api('schema?page=' + name); } catch (e) { root.append(el('p', 'chelp', 'Impossible de charger cette page.')); return; }
    if (current !== name) return;
    sc.sections.forEach((sec) => root.append(sectionCard(sec, EXTRAS[name] && EXTRAS[name][sec.title])));
    if (BOTTOM[name]) BOTTOM[name](root);
    root.scrollTop = 0;
  }
  window.openPage = openPage;
})();
