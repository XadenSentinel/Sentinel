(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const token = new URLSearchParams(location.hash.slice(1)).get('t') || '';
  const STATE_LABEL = {
    loading: 'Initialisation', idle: 'En veille', listening: 'Je vous écoute', thinking: 'Traitement…',
    speaking: 'Réponse', off: 'Écoute coupée', nomodel: 'Modèle vocal manquant', error: 'Erreur',
  };
  const RAIL = 210, SIDE = 300;

  let snap = null, sphere = null, entered = false, listening = true, micReady = false, brainOk = null, brainOn = true;
  let state = 'loading', typeTimer = null, timers = [], timersAt = 0, chat = [];
  const store = { get: () => { try { return JSON.parse(localStorage.getItem('sentinel_chat') || '[]'); } catch (e) { return []; } },
                  set: (v) => { try { localStorage.setItem('sentinel_chat', JSON.stringify(v.slice(-200))); } catch (e) { /* stockage indisponible */ } } };

  async function api(path, body) {
    const r = await fetch('/api/' + path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(token), body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }
  const core = { api, action: null, toast: null, snap: null, listeners: {}, on(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
                 off(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); } };
  window.core = core;

  const action = (name, data) => api('action', { name, data: data || {} }).catch(() => { toast('Sentinel ne répond pas.'); return { ok: false }; });
  core.action = action;

  function toast(text) {
    const t = $('toast'); t.textContent = text; t.classList.remove('hidden');
    clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.add('hidden'), 3200);
  }

  core.toast = toast;

  // ------------------------------------------------------------------ apparence
  function hexToRgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function applyAccent(hex) {
    const root = document.documentElement.style;
    root.setProperty('--accent', hex); root.setProperty('--accent-rgb', hexToRgb(hex).join(','));
    if (sphere) sphere.setColor(hex);
    document.querySelectorAll('.sw').forEach((b) => b.classList.toggle('sel', b.dataset.hex.toLowerCase() === hex.toLowerCase()));
    $('customColor').value = hex;
  }
  function applyPalette(p) {
    if (!p) return;
    const r = document.documentElement.style, rgb = (h) => hexToRgb(h).join(',');
    r.setProperty('--bg', p.bg); r.setProperty('--text', p.text); r.setProperty('--dim', p.dim);
    r.setProperty('--panel', 'rgba(' + rgb(p.panel) + ',.62)'); r.setProperty('--line', 'rgba(' + rgb(p.text) + ',.14)');
    r.setProperty('--grad-top', p.grad[0]); r.setProperty('--grad-bottom', p.grad[1]);
  }
  let lastDensity = null;
  function applySnapshot(s) {
    snap = Object.assign(snap || {}, s); core.snap = snap;
    applyPalette(s.palette); applyAccent(s.accent);
    document.title = s.brand; $('brand').textContent = s.brand.toUpperCase(); $('railBrand').textContent = s.brand;
    $('hint').textContent = 'Dites « ' + s.wake + ' » puis votre commande';
    document.body.classList.toggle('fx', !!s.fx);
    brainOn = s.brain !== false;
    if (sphere && lastDensity !== null && s.density !== lastDensity) sphere.setDensity(s.density);
    lastDensity = s.density;
    if ($('density')) { $('density').value = s.density; $('densVal').textContent = s.density; }
    $('fx').checked = !!s.fx; $('skipIntro').checked = !!s.skip_intro;
  }
  core.applySnapshot = applySnapshot;
  function applyInsets() {
    if (!sphere) return;
    const wide = window.innerWidth > 980;
    sphere.setInset(entered && !$('view-home').classList.contains('hidden') ? RAIL : 0, entered && wide && !$('view-home').classList.contains('hidden') ? SIDE : 0);
  }

  // ------------------------------------------------------------------ état
  function setState(s) {
    state = s;
    $('stateLabel').textContent = STATE_LABEL[s] || s;
    if (sphere) sphere.setState(s);
    listening = s !== 'off';
    $('btnMute').classList.toggle('off', !listening);
    $('btnMute').querySelector('.dot').className = 'dot ' + (listening ? 'ok' : 'bad');
    $('muteText').textContent = listening ? 'Écoute' : 'Écoute coupée';
    const mic = $('pillMic');
    mic.querySelector('.dot').className = 'dot ' + (s === 'off' ? 'bad' : s === 'loading' ? 'wait' : 'ok');
    mic.lastElementChild.textContent = s === 'off' ? 'Micro coupé' : 'Micro';
    updateStartStatus();
  }
  function updateStartStatus() {
    const dot = document.querySelector('#startStatus .dot'), txt = $('startStatusText');
    if (state === 'nomodel') { dot.className = 'dot bad'; txt.textContent = 'Modèle vocal manquant : ouvre les réglages avancés'; return; }
    if (!micReady) { dot.className = 'dot wait'; txt.textContent = 'Initialisation du micro et de la voix…'; return; }
    dot.className = 'dot ok';
    txt.textContent = 'Prêt' + (brainOn ? (brainOk === null ? ' · vérification de l\'IA…' : brainOk ? ' · IA en ligne' : ' · IA hors ligne') : '');
  }
  function typewriter(el, text) {
    clearInterval(typeTimer); el.textContent = ''; let i = 0;
    typeTimer = setInterval(() => { el.textContent = text.slice(0, ++i); if (i >= text.length) clearInterval(typeTimer); }, 16);
  }

  // ------------------------------------------------------------------ événements
  function onEvent(ev) {
    const a = ev.a || [];
    (core.listeners[ev.t] || []).forEach((fn) => { try { fn.apply(null, a); } catch (e) { console.error(e); } });
    switch (ev.t) {
      case 'state': setState(a[0]); break;
      case 'level': if (sphere) sphere.setLevel(a[0]); break;
      case 'log': onLog(a[0], a[1]); break;
      case 'ready': micReady = true; updateStartStatus(); break;
      case 'brain': {
        const st = a[0] || {}; brainOk = !!st.ok;
        const pill = $('pillIA');
        pill.querySelector('.dot').className = 'dot ' + (!brainOn ? '' : brainOk ? 'ok' : 'bad');
        pill.lastElementChild.textContent = !brainOn ? 'IA désactivée' : brainOk ? 'IA · ' + (st.model || 'en ligne') : 'IA hors ligne';
        updateStartStatus(); break;
      }
      case 'weather': renderWeather(a[0], a[1]); break;
      case 'timers': timers = a[0] || []; timersAt = Date.now(); renderTimers(); break;
      case 'telemetry': meter('Cpu', a[0]); meter('Ram', a[1]); break;
      case 'apps_indexed': $('kvApps').textContent = Number(a[0]).toLocaleString('fr-FR'); break;
      case 'files_indexed': $('kvFiles').textContent = Number(a[0]).toLocaleString('fr-FR'); break;
      case 'update':
        if (a[0] === 'available' && a[1]) {
          const p = $('pillUpdate'); p.textContent = 'Mise à jour ' + a[1].version; p.classList.remove('hidden');
        }
        break;
      case 'interaction': if (a[0]) showLearn(a[0]); break;
      default: break;
    }
  }
  function onLog(kind, msg) {
    if (kind === 'cmd') {
      $('heard').textContent = '« ' + msg + ' »'; $('reply').textContent = ''; $('learn').classList.add('hidden');
      addChat('user', msg);
    } else if (kind === 'reply') {
      typewriter($('reply'), msg); addChat('bot', msg);
    } else if (kind === 'error') {
      toast(String(msg).slice(0, 140));
    }
  }
  function meter(name, v) { $('bar' + name).style.width = Math.max(0, Math.min(100, v)) + '%'; $('val' + name).textContent = Math.round(v) + '%'; }
  const WX = (c) => c === 0 ? '☀' : c <= 3 ? '⛅' : c <= 48 ? '☁' : c <= 67 ? '☂' : c <= 77 ? '❄' : c <= 82 ? '☂' : '⚡';
  function renderWeather(d, reason) {
    if (d) {
      $('wxMain').textContent = WX(d.code) + '  ' + d.temp + '°C';
      let sub = d.city + ' · ' + d.desc;
      if (d.tmin != null && d.tmax != null) sub += '\nmin ' + d.tmin + '° · max ' + d.tmax + '°';
      if (d.rain != null) sub += ' · pluie ' + d.rain + ' %';
      $('wxSub').textContent = sub; $('wxSub').style.whiteSpace = 'pre-line';
    } else {
      $('wxMain').textContent = '—';
      $('wxSub').textContent = { no_city: 'Indique ta ville dans les réglages avancés.', city_unknown: 'Ville introuvable.', network: 'Météo indisponible (pas de connexion ?).' }[reason] || '';
    }
  }
  const fmt = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
  function renderTimers() {
    const box = $('timers');
    if (!timers.length) { box.textContent = 'Aucun en cours'; return; }
    const spent = (Date.now() - timersAt) / 1000;
    box.innerHTML = '';
    timers.forEach((t) => {
      const row = document.createElement('div'); row.className = 'timer';
      const l = document.createElement('span'); l.textContent = t.label || 'Minuteur';
      const r = document.createElement('span'); r.textContent = fmt(t.left - spent);
      row.append(l, r); box.append(row);
    });
  }

  // ------------------------------------------------------------------ conversation
  function addChat(role, text) {
    chat.push({ r: role, t: text, ts: Date.now() }); store.set(chat); renderChat();
  }
  function renderChat() {
    const list = $('chatList'); list.innerHTML = '';
    if (!chat.length) {
      const e = document.createElement('div'); e.className = 'empty';
      e.textContent = 'Aucun échange pour l\'instant. Dis « ' + (snap ? snap.wake : 'Sentinel') + ' » puis ta demande, ou écris-la ci-dessous.';
      list.append(e); return;
    }
    chat.forEach((m) => {
      const d = document.createElement('div'); d.className = 'msg ' + (m.r === 'user' ? 'user' : 'bot');
      d.textContent = m.t;
      const s = document.createElement('small'); s.textContent = new Date(m.ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
      d.append(s); list.append(d);
    });
    list.scrollTop = list.scrollHeight;
  }

  // ------------------------------------------------------------------ navigation
  const PAGE_VIEWS = ['commands', 'apps', 'music', 'discord', 'brain', 'voice', 'replies', 'permissions', 'settings', 'log'];
  function showView(name) {
    const isPage = PAGE_VIEWS.includes(name);
    $('view-home').classList.toggle('hidden', name !== 'home');
    $('view-chat').classList.toggle('hidden', name !== 'chat');
    $('view-page').classList.toggle('hidden', !isPage);
    document.querySelectorAll('.nav[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
    document.body.classList.toggle('view-chat', name === 'chat');
    document.body.classList.toggle('view-page', isPage);
    if (name === 'chat') { renderChat(); setTimeout(() => $('chatInput').focus(), 50); }
    if (isPage && window.openPage) window.openPage(name);
    applyInsets();
  }
  core.showView = showView;

  // ------------------------------------------------------------------ fenêtres modales (bienvenue, correction)
  function openModal(build) {
    const box = $('modalBox'); box.innerHTML = ''; build(box); $('modal').classList.remove('hidden');
    const first = box.querySelector('input,select'); if (first) setTimeout(() => first.focus(), 30);
  }
  function closeModal() { $('modal').classList.add('hidden'); }
  core.openModal = openModal; core.closeModal = closeModal;
  const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  function field(box, label, control) { box.append(mk('label', '', label), control); return control; }

  function teachDialog(inter) {
    openModal((box) => {
      box.append(mk('h3', '', 'Apprendre de mon erreur'));
      const info = mk('p', '', 'J\'ai entendu : « ' + inter.heard + ' »\nJ\'ai compris : ' + inter.understood); info.style.whiteSpace = 'pre-line'; box.append(info);
      const inp = field(box, 'Qu\'est-ce que tu voulais vraiment ?', mk('input')); inp.type = 'text'; inp.placeholder = 'ex. ouvre Discord   ·   mets Life de Damso sur Spotify';
      const note = mk('p', 'small', 'La prochaine fois que tu diras cette phrase (ou une très proche), Sentinel fera directement ce que tu écris ici.'); note.style.marginTop = '12px'; box.append(note);
      const row = mk('div', 'modal-actions');
      const go = (rerun) => { const m = inp.value.trim(); if (!m) { inp.focus(); return; } action('teach', { heard: inter.heard, meant: m, rerun }).then(() => { toast('Appris ✓'); closeModal(); }); };
      const b1 = mk('button', 'btn primary', 'Apprendre et refaire'), b2 = mk('button', 'btn', 'Apprendre seulement'), b3 = mk('button', 'btn', 'Annuler');
      b1.onclick = () => go(true); b2.onclick = () => go(false); b3.onclick = closeModal;
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(true); });
      row.append(b1, b2, b3); box.append(row);
    });
  }
  let lastInter = null;
  function showLearn(inter) {
    lastInter = inter; $('learn').classList.remove('hidden');
    $('learnText').textContent = 'Compris : ' + inter.understood;
  }

  function wizard() {
    openModal((box) => {
      box.append(mk('h3', '', 'Bienvenue'));
      box.append(mk('p', '', 'Quelques questions pour personnaliser ton assistant. Tout se change plus tard dans les paramètres.'));
      const name = field(box, 'Comment dois-je t\'appeler ?', mk('input')); name.type = 'text'; name.placeholder = 'ton prénom';
      const wake = field(box, 'Mot pour m\'appeler', mk('input')); wake.type = 'text'; wake.value = (snap.wake || 'Sentinel').toLowerCase(); wake.placeholder = 'ex. sentinel, jarvis, friday…';
      const city = field(box, 'Ta ville (pour la météo)', mk('input')); city.type = 'text'; city.placeholder = 'ex. Lille';
      const voice = field(box, 'Ma voix', mk('select'));
      [['male', 'Voix d\'homme (Henri)'], ['female', 'Voix de femme (Denise)']].forEach(([v, l]) => { const o = mk('option', '', l); o.value = v; voice.append(o); });
      const style = field(box, 'Ma façon de parler', mk('select'));
      [['jarvis', 'Jarvis — formel, vouvoiement'], ['cool', 'Décontracté — tutoiement'], ['court', 'Court — le strict minimum']].forEach(([v, l]) => { const o = mk('option', '', l); o.value = v; style.append(o); });
      const row = mk('div', 'modal-actions'), ok = mk('button', 'btn primary', 'Terminer'), later = mk('button', 'btn', 'Plus tard');
      const send = (data) => action('wizard', data).then((r) => { if (r.snapshot) applySnapshot(r.snapshot); closeModal(); });
      ok.onclick = () => send({ user_name: name.value, wake_word: wake.value, weather_city: city.value, voice: voice.value, style: style.value });
      later.onclick = () => send({ user_name: '', wake_word: (snap.wake || 'sentinel').toLowerCase(), weather_city: '', voice: 'male', style: 'jarvis' });
      row.append(ok, later); box.append(row);
    });
  }

  function enterHome(instant) {
    if (entered) return;
    entered = true;
    const reveal = () => {
      $('start').classList.add('hidden'); $('hud').classList.remove('hidden');
      requestAnimationFrame(() => $('hud').classList.add('show'));
      applyInsets();
    };
    if (instant) { sphere.setMode('home', true); reveal(); return; }
    $('start').classList.add('leaving');
    sphere.playIntro({
      d1: 1500, d2: 1400,
      onMid: () => { $('flash').classList.remove('go'); void $('flash').offsetWidth; $('flash').classList.add('go'); reveal(); },
    });
    action('start');
  }

  // ------------------------------------------------------------------ panneau d'apparence
  function buildLook() {
    const box = $('swatches');
    Object.entries(snap.accents).forEach(([name, hex]) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'sw'; b.style.background = hex; b.dataset.hex = hex; b.title = name;
      b.addEventListener('click', () => { applyAccent(hex); api('setting', { key: 'custom_accent', value: '' }).then(() => api('setting', { key: 'accent', value: name })); });
      box.append(b);
    });
    $('customColor').addEventListener('input', (e) => { applyAccent(e.target.value); clearTimeout(buildLook.h);
      buildLook.h = setTimeout(() => api('setting', { key: 'custom_accent', value: e.target.value }), 300); });
    const dens = $('density'); dens.value = snap.density; $('densVal').textContent = snap.density;
    dens.addEventListener('input', () => { $('densVal').textContent = dens.value; sphere.setDensity(+dens.value); clearTimeout(buildLook.d);
      buildLook.d = setTimeout(() => api('setting', { key: 'sphere_density', value: +dens.value }), 400); });
    $('fx').checked = snap.fx; document.body.classList.toggle('fx', snap.fx);
    $('fx').addEventListener('change', (e) => { document.body.classList.toggle('fx', e.target.checked); api('setting', { key: 'hud_fx', value: e.target.checked }); });
    $('skipIntro').checked = snap.skip_intro;
    $('skipIntro').addEventListener('change', (e) => api('setting', { key: 'skip_intro', value: e.target.checked }));
  }

  // ------------------------------------------------------------------ démarrage
  function tickClock() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    $('date').textContent = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
    renderTimers();
  }

  function connect() {
    const es = new EventSource('/api/events?t=' + encodeURIComponent(token));
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.error(e); } };
    es.onerror = () => { $('startStatusText').textContent = 'Connexion perdue… nouvelle tentative'; };
  }

  async function init() {
    try { snap = await api('state'); } catch (e) {
      document.querySelector('.start-inner').innerHTML = '<p class="startStatus">Session expirée : rouvre l\'interface depuis l\'icône de Sentinel (zone de notification).</p>';
      return;
    }
    document.title = snap.brand; brainOn = snap.brand !== undefined ? snap.brain !== false : true;
    $('brand').textContent = snap.brand.toUpperCase(); $('railBrand').textContent = snap.brand; $('ver').textContent = 'v' + snap.version;
    $('hint').textContent = 'Dites « ' + snap.wake + ' » puis votre commande';
    chat = store.get();
    sphere = createSphere($('sphere'), { density: snap.density, onDegrade: (n) => toast('Sphère allégée (' + n + ' particules) pour rester fluide.') });
    window.__sphere = sphere;
    core.snap = snap; applyPalette(snap.palette); lastDensity = snap.density;
    applyAccent(snap.accent);
    sphere.setMode('start', true);
    buildLook(); tickClock(); setInterval(tickClock, 1000);
    setState(snap.state || 'loading');
    connect();
    window.addEventListener('resize', applyInsets);

    $('btnStart').addEventListener('click', () => enterHome(false));
    $('btnClassicStart').addEventListener('click', () => action('open_classic', { page: 'settings' }));
    $('btnQuitStart').addEventListener('click', () => action('quit'));
    $('btnQuit').addEventListener('click', () => { toast('Sentinel s\'arrête…'); action('quit'); });
    document.querySelectorAll('.nav[data-view]').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
    document.querySelectorAll('.nav[data-classic]').forEach((b) => b.addEventListener('click', () => { action('open_classic', { page: b.dataset.classic }); toast('Ouverture de la fenêtre des réglages…'); }));
    $('pillUpdate').addEventListener('click', () => showView('settings'));
    $('btnOk').addEventListener('click', () => action('confirm').then((r) => { $('learn').classList.add('hidden'); toast(r.kept ? 'Merci, je retiens cet exemple ✓' : 'Merci ✓'); }));
    $('btnBad').addEventListener('click', () => lastInter && teachDialog(lastInter));
    $('modal').addEventListener('click', (e) => { if (e.target === $('modal')) closeModal(); });
    $('btnTalk').addEventListener('click', () => action('trigger'));
    $('btnMute').addEventListener('click', () => action('listen', { on: !listening }));
    $('btnGear').addEventListener('click', () => $('look').classList.toggle('hidden'));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('look').classList.add('hidden'); });
    $('cmdForm').addEventListener('submit', (e) => { e.preventDefault(); const t = $('cmdInput').value.trim(); if (t) { action('command', { text: t }); $('cmdInput').value = ''; } });
    $('chatForm').addEventListener('submit', (e) => { e.preventDefault(); const t = $('chatInput').value.trim(); if (t) { action('command', { text: t }); $('chatInput').value = ''; } });
    $('btnClear').addEventListener('click', () => { chat = []; store.set(chat); renderChat(); });
    renderChat();
    if (snap.skip_intro) enterHome(true);
    if (snap.first_run) setTimeout(wizard, snap.skip_intro ? 400 : 200);
  }
  init();
})();
