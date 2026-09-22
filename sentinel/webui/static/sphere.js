(function (global) {
  'use strict';

  const CAM = 3.2;
  const PRESETS = {
    loading:   { rot: .0058, pulses: 70,  speed: .055, breath: .010, wave: 0, sweep: 0, bright: .85 },
    idle:      { rot: .0026, pulses: 26,  speed: .035, breath: .015, wave: 0, sweep: 0, bright: .95 },
    listening: { rot: .0034, pulses: 50,  speed: .050, breath: .015, wave: 0, sweep: 0, bright: 1.0 },
    thinking:  { rot: .0090, pulses: 130, speed: .075, breath: .010, wave: 0, sweep: 1, bright: 1.0 },
    speaking:  { rot: .0042, pulses: 85,  speed: .058, breath: .010, wave: 1, sweep: 0, bright: 1.0 },
    off:       { rot: .0008, pulses: 6,   speed: .020, breath: .006, wave: 0, sweep: 0, bright: .35 },
  };
  PRESETS.nomodel = PRESETS.off;
  PRESETS.error = PRESETS.off;
  const LAYOUTS = { start: { scale: 1.38, offY: -0.02 }, home: { scale: 0.84, offY: 0.12 } };
  const MAX_PULSES = 260;

  function mulberry(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hexToRgb(hex) {
    const h = /^#[0-9a-f]{6}$/i.test(hex) ? hex : '#00e5ff';
    return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
  }

  function buildGeometry(N) {
    const rnd = mulberry(1234);
    const pos = new Float32Array(N * 4);
    for (let i = 0; i < N; i++) {
      const y = 1 - 2 * (i + 0.5) / N, r = Math.sqrt(1 - y * y), a = i * 2.399963229728653;
      const s = (i % 4 === 0) ? 0.55 + 0.25 * rnd() : 0.93 + 0.07 * rnd();
      pos[i * 4] = Math.cos(a) * r * s; pos[i * 4 + 1] = y * s; pos[i * 4 + 2] = Math.sin(a) * r * s; pos[i * 4 + 3] = rnd();
    }
    const cell = 3.54 / Math.sqrt(N) * 2.4, inv = 1 / cell, off = 1.1, dim = Math.ceil(2.2 * inv) + 2;
    const grid = new Map();
    const cidx = (v) => Math.max(0, Math.min(dim - 1, Math.floor((v + off) * inv)));
    const ckey = (x, y, z) => (x * dim + y) * dim + z;
    for (let i = 0; i < N; i++) {
      const k = ckey(cidx(pos[i * 4]), cidx(pos[i * 4 + 1]), cidx(pos[i * 4 + 2]));
      (grid.get(k) || grid.set(k, []).get(k)).push(i);
    }
    const seen = new Set(), edges = [], adj = Array.from({ length: N }, () => []);
    for (let i = 0; i < N; i++) {
      const px = pos[i * 4], py = pos[i * 4 + 1], pz = pos[i * 4 + 2];
      const cx = cidx(px), cy = cidx(py), cz = cidx(pz);
      const best = [[9, -1], [9, -1], [9, -1]];
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
        const list = grid.get(ckey(cx + dx, cy + dy, cz + dz));
        if (!list) continue;
        for (const j of list) {
          if (j === i) continue;
          const ex = px - pos[j * 4], ey = py - pos[j * 4 + 1], ez = pz - pos[j * 4 + 2], d = ex * ex + ey * ey + ez * ez;
          if (d < best[2][0]) {
            best[2] = [d, j];
            if (best[2][0] < best[1][0]) { const t = best[1]; best[1] = best[2]; best[2] = t; }
            if (best[1][0] < best[0][0]) { const t = best[0]; best[0] = best[1]; best[1] = t; }
          }
        }
      }
      for (const b of best) {
        const j = b[1];
        if (j < 0) continue;
        const k = i < j ? i * N + j : j * N + i;
        if (!seen.has(k)) { seen.add(k); edges.push(i, j); adj[i].push(j); adj[j].push(i); }
      }
    }
    return { N, pos, edges: Uint32Array.from(edges), adj };
  }

  class Core {
    constructor(canvas, opts) {
      this.canvas = canvas;
      this.opts = opts || {};
      this.color = [0, 0.9, 1];
      this.stateName = 'loading';
      this.p = Object.assign({}, PRESETS.loading);
      this.rot = 0; this.t = 0; this.level = 0; this.lv = 0;
      this.lay = Object.assign({}, LAYOUTS.start); this.layT = Object.assign({}, LAYOUTS.start);
      this.insL = 0; this.insR = 0;
      this.pulses = [];
      this.intro = null;
      this.last = 0; this.slow = 0; this.frames = 0; this.auto = true;
      this.geo = null;
      this.running = true;
      this.dpr = 1; this.W = 1; this.H = 1;
    }
    setColor(hex) { this.color = hexToRgb(hex); }
    setLevel(v) { this.level = Math.max(0, Math.min(1, v * 7)); }
    setState(s) { this.stateName = PRESETS[s] ? s : 'idle'; }
    setMode(m, instant) { this.layT = Object.assign({}, LAYOUTS[m] || LAYOUTS.home); if (instant) this.lay = Object.assign({}, this.layT); }
    setInset(left, right) { this.insL = left; this.insR = right; }
    setDensity(n) {
      n = Math.max(400, Math.min(5000, Math.round(n)));
      if (this.geo && this.geo.N === n) return;
      this.geo = buildGeometry(n);
      this.pulses = [];
      this.onGeometry();
    }
    onGeometry() {}
    playIntro(o) { this.intro = Object.assign({ t0: performance.now(), d1: 1500, d2: 1300, midDone: false }, o || {}); }
    resize() {
      const rect = this.canvas.getBoundingClientRect();
      this.dpr = Math.min(2, global.devicePixelRatio || 1);
      this.W = Math.max(2, Math.round(rect.width * this.dpr));
      this.H = Math.max(2, Math.round(rect.height * this.dpr));
      if (this.canvas.width !== this.W) this.canvas.width = this.W;
      if (this.canvas.height !== this.H) this.canvas.height = this.H;
    }
    step(now) {
      const dt = Math.min(0.05, (now - (this.last || now)) / 1000);
      this.last = now; this.t += dt;
      const target = PRESETS[this.stateName], k = Math.min(1, dt * 3);
      for (const key in target) this.p[key] += (target[key] - this.p[key]) * k;
      const kl = Math.min(1, dt * 4);
      for (const key in this.layT) this.lay[key] += (this.layT[key] - this.lay[key]) * kl;
      this.lv += (this.level - this.lv) * Math.min(1, dt * 12);
      this.cam = CAM; this.boost = 1; this.sizeK = 1;
      let rotK = 1;
      const it = this.intro;
      if (it) {
        const e = now - it.t0;
        if (e < it.d1) {
          const u = e / it.d1;
          this.cam = CAM + (0.22 - CAM) * u * u * u; rotK = 1 + 14 * u * u; this.sizeK = 1 + 0.9 * u; this.boost = 1 + u;
        } else {
          if (!it.midDone) { it.midDone = true; this.setMode('home', true); if (it.onMid) it.onMid(); }
          const u = Math.min(1, (e - it.d1) / it.d2), inv = 1 - u;
          this.cam = 0.22 + (CAM - 0.22) * (1 - inv * inv * inv); rotK = 1 + 10 * inv * inv; this.sizeK = 1 + 0.9 * inv; this.boost = 1 + inv;
          if (u >= 1) { this.intro = null; if (it.onEnd) it.onEnd(); }
        }
      }
      this.rot += this.p.rot * dt * 60 * rotK;
      this.sweep = Math.sin(this.t * 1.6) * 0.9;
      this.advancePulses(dt);
      this.watchPerformance(dt);
    }
    advancePulses(dt) {
      const g = this.geo, want = Math.min(MAX_PULSES, Math.round(this.p.pulses));
      while (this.pulses.length < want) {
        const a = Math.floor(Math.random() * g.N), nb = g.adj[a];
        if (nb.length) this.pulses.push({ a, b: nb[Math.floor(Math.random() * nb.length)], t: Math.random() });
      }
      if (this.pulses.length > want) this.pulses.length = want;
      const sp = this.p.speed * dt * 60;
      for (const q of this.pulses) {
        q.t += sp;
        if (q.t >= 1) {
          const opts = g.adj[q.b].filter((j) => j !== q.a), prev = q.b;
          q.a = prev; q.b = opts.length ? opts[Math.floor(Math.random() * opts.length)] : q.a; q.t = 0;
        }
      }
    }
    watchPerformance(dt) {
      if (!this.auto || this.intro) return;
      this.warm = (this.warm || 0) + 1;
      if (this.warm < 240) return;                       // on ignore le chargement de la page
      this.frames++; this.slow += dt;
      if (this.frames >= 120) {
        const avg = this.slow / this.frames;
        this.frames = 0; this.slow = 0;
        if (avg > 0.042 && this.geo.N > 700) {
          this.setDensity(this.geo.N * 0.7);
          if (this.opts.onDegrade) this.opts.onDegrade(this.geo.N);
        }
      }
    }
    loop = (now) => {
      if (!this.running) return;
      this.step(now); this.draw();
      global.requestAnimationFrame(this.loop);
    };
    start() { this.resize(); global.requestAnimationFrame(this.loop); }
    destroy() { this.running = false; }
    layoutX() { return (this.insL - this.insR) / Math.max(1, this.W / this.dpr) * Math.max(0, Math.min(1, (1.3 - this.lay.scale) / 0.3)); }
  }

  const VS = `
precision highp float;
attribute vec4 aP;
uniform float uT,uRot,uTilt,uBreath,uWave,uSweep,uSweepAmt,uLevel,uCam,uAsp,uScale,uOffX,uOffY,uPx,uSize,uMode;
varying float vDepth,vGlow,vK;
void main(){
  vec3 p0=aP.xyz; float w=aP.w; vec3 p=p0;
  float wv=sin(p0.y*7.0-uT*5.0);
  float k=1.0+uBreath+0.07*uLevel+0.06*uWave*wv*(0.6+0.4*sin(uT*2.3));
  p*=k;
  float ca=cos(uRot),sa=sin(uRot);
  vec3 q=vec3(p.x*ca+p.z*sa,p.y,-p.x*sa+p.z*ca);
  float ct=cos(uTilt),st=sin(uTilt);
  vec3 r=vec3(q.x,q.y*ct-q.z*st,q.y*st+q.z*ct);
  float d=uCam-r.z;
  float g=0.0;
  if(uMode<0.5){
    g+=uSweepAmt*max(0.0,1.0-abs(p0.y-uSweep)/0.16);
    g+=uWave*max(0.0,wv)*0.45;
    g+=step(0.83,fract(w*13.7))*uLevel*0.8;
  } else if(uMode<1.5){ g=1.0; }
  if(d<0.06){ gl_Position=vec4(3.0,3.0,0.0,1.0); gl_PointSize=1.0; vDepth=0.0; vGlow=0.0; vK=0.0; return; }
  float f=2.0*uScale;
  gl_Position=vec4(r.x*f/d/uAsp+uOffX, r.y*f/d+uOffY, 0.0, 1.0);
  gl_PointSize=clamp(uSize*uPx*(3.2/d),1.0,70.0);
  vDepth=clamp((r.z+1.0)*0.5,0.0,1.0); vGlow=g; vK=w;
}`;
  const FS = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec3 uColor; uniform float uAlpha,uMode,uBright;
varying float vDepth,vGlow,vK;
void main(){
  if(uMode>1.5){ gl_FragColor=vec4(uColor,uAlpha*uBright*(0.25+0.75*vDepth)); return; }
  vec2 c=gl_PointCoord-0.5; float d=length(c)*2.0; if(d>1.0) discard;
  float soft=pow(1.0-d,1.7);
  vec3 col=mix(uColor,vec3(1.0),clamp(vGlow,0.0,1.0)*0.8);
  float br=(0.3+0.7*vDepth*vDepth)+vGlow*0.9;
  if(uMode>0.5) br=vK;
  gl_FragColor=vec4(col,soft*br*uAlpha*uBright);
}`;

  class GLSphere extends Core {
    constructor(canvas, opts) {
      super(canvas, opts);
      const gl = canvas.getContext('webgl', { antialias: false, alpha: true, premultipliedAlpha: true });
      if (!gl) throw new Error('WebGL indisponible');
      this.gl = gl;
      const sh = (type, src) => {
        const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error('shader : ' + gl.getShaderInfoLog(s));
        return s;
      };
      const prog = gl.createProgram();
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('programme : ' + gl.getProgramInfoLog(prog));
      this.prog = prog;
      this.loc = gl.getAttribLocation(prog, 'aP');
      this.U = {};
      ['uT', 'uRot', 'uTilt', 'uBreath', 'uWave', 'uSweep', 'uSweepAmt', 'uLevel', 'uCam', 'uAsp', 'uScale', 'uOffX', 'uOffY', 'uPx', 'uSize', 'uMode', 'uColor', 'uAlpha', 'uBright']
        .forEach((n) => { this.U[n] = gl.getUniformLocation(prog, n); });
      this.nodeBuf = gl.createBuffer(); this.lineBuf = gl.createBuffer(); this.pulseBuf = gl.createBuffer();
      this.pulseData = new Float32Array(MAX_PULSES * 3 * 4);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.pulseBuf);
      gl.bufferData(gl.ARRAY_BUFFER, this.pulseData.byteLength, gl.DYNAMIC_DRAW);
      canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); if (this.opts.onLost) this.opts.onLost(); });
      this.renderer = 'webgl';
    }
    onGeometry() {
      const gl = this.gl, g = this.geo;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.nodeBuf); gl.bufferData(gl.ARRAY_BUFFER, g.pos, gl.STATIC_DRAW);
      const lines = new Float32Array(g.edges.length * 4);
      for (let e = 0; e < g.edges.length; e++) {
        const n = g.edges[e];
        lines[e * 4] = g.pos[n * 4]; lines[e * 4 + 1] = g.pos[n * 4 + 1]; lines[e * 4 + 2] = g.pos[n * 4 + 2]; lines[e * 4 + 3] = 0;
      }
      this.lineCount = g.edges.length;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuf); gl.bufferData(gl.ARRAY_BUFFER, lines, gl.STATIC_DRAW);
    }
    draw() {
      const gl = this.gl, g = this.geo, U = this.U;
      this.resize();
      gl.viewport(0, 0, this.W, this.H);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE, gl.ONE, gl.ONE);
      gl.useProgram(this.prog);
      gl.uniform1f(U.uT, this.t); gl.uniform1f(U.uRot, this.rot); gl.uniform1f(U.uTilt, 0.38);
      gl.uniform1f(U.uBreath, this.p.breath * (1 + 0.6 * Math.sin(this.t * 1.2)));
      gl.uniform1f(U.uWave, this.p.wave);
      gl.uniform1f(U.uSweep, this.sweep); gl.uniform1f(U.uSweepAmt, this.p.sweep);
      gl.uniform1f(U.uLevel, this.lv); gl.uniform1f(U.uCam, this.cam);
      gl.uniform1f(U.uAsp, this.W / this.H); gl.uniform1f(U.uScale, this.lay.scale);
      gl.uniform1f(U.uOffX, this.layoutX()); gl.uniform1f(U.uOffY, this.lay.offY);
      gl.uniform1f(U.uPx, this.dpr); gl.uniform3fv(U.uColor, this.color);
      gl.uniform1f(U.uBright, this.p.bright * this.boost);
      gl.enableVertexAttribArray(this.loc);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuf); gl.vertexAttribPointer(this.loc, 4, gl.FLOAT, false, 16, 0);
      gl.uniform1f(U.uMode, 2); gl.uniform1f(U.uAlpha, 0.2); gl.uniform1f(U.uSize, 1);
      gl.drawArrays(gl.LINES, 0, this.lineCount);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.nodeBuf); gl.vertexAttribPointer(this.loc, 4, gl.FLOAT, false, 16, 0);
      gl.uniform1f(U.uMode, 0); gl.uniform1f(U.uAlpha, 0.95); gl.uniform1f(U.uSize, 3.9 * this.sizeK);
      gl.drawArrays(gl.POINTS, 0, g.N);
      const n = this.fillPulses();
      if (n) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.pulseBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.pulseData.subarray(0, n * 4));
        gl.vertexAttribPointer(this.loc, 4, gl.FLOAT, false, 16, 0);
        gl.uniform1f(U.uMode, 1); gl.uniform1f(U.uAlpha, 1); gl.uniform1f(U.uSize, 5.2 * this.sizeK);
        gl.drawArrays(gl.POINTS, 0, n);
      }
    }
    fillPulses() {
      const g = this.geo, pos = g.pos, out = this.pulseData;
      let n = 0;
      for (const q of this.pulses) {
        for (let s = 0; s < 3; s++) {
          const t = Math.max(0, q.t - s * 0.08), a = q.a * 4, b = q.b * 4;
          out[n * 4] = pos[a] + (pos[b] - pos[a]) * t;
          out[n * 4 + 1] = pos[a + 1] + (pos[b + 1] - pos[a + 1]) * t;
          out[n * 4 + 2] = pos[a + 2] + (pos[b + 2] - pos[a + 2]) * t;
          out[n * 4 + 3] = s === 0 ? 1 : s === 1 ? 0.5 : 0.22;
          n++;
        }
      }
      return n;
    }
  }

  class CanvasSphere extends Core {
    constructor(canvas, opts) {
      super(canvas, opts);
      this.ctx = canvas.getContext('2d');
      this.renderer = 'canvas2d';
    }
    project(x, y, z, w, h) {
      const k = 1 + this.p.breath + 0.07 * this.lv + 0.06 * this.p.wave * Math.sin(y * 7 - this.t * 5);
      x *= k; y *= k; z *= k;
      const ca = Math.cos(this.rot), sa = Math.sin(this.rot), ct = Math.cos(0.38), st = Math.sin(0.38);
      const qx = x * ca + z * sa, qz = -x * sa + z * ca, ry = y * ct - qz * st, rz = y * st + qz * ct;
      const d = this.cam - rz;
      if (d < 0.06) return null;
      const f = 2 * this.lay.scale, asp = w / h;
      return [(((qx * f / d) / asp + this.layoutX()) * 0.5 + 0.5) * w, (0.5 - (ry * f / d + this.lay.offY) * 0.5) * h, d, Math.max(0, Math.min(1, (rz + 1) / 2))];
    }
    draw() {
      this.resize();
      const ctx = this.ctx, g = this.geo, W = this.W, H = this.H, c = this.color.map((v) => Math.round(v * 255));
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
      const P = new Array(g.N);
      for (let i = 0; i < g.N; i++) P[i] = this.project(g.pos[i * 4], g.pos[i * 4 + 1], g.pos[i * 4 + 2], W, H);
      const buckets = [new Path2D(), new Path2D(), new Path2D()];
      for (let e = 0; e < g.edges.length; e += 2) {
        const a = P[g.edges[e]], b = P[g.edges[e + 1]];
        if (!a || !b) continue;
        const q = (a[3] + b[3]) / 2 < 0.4 ? 0 : (a[3] + b[3]) / 2 < 0.7 ? 1 : 2;
        buckets[q].moveTo(a[0], a[1]); buckets[q].lineTo(b[0], b[1]);
      }
      const br = this.p.bright * this.boost;
      ctx.lineWidth = Math.max(1, this.dpr * 0.6);
      [0.07, 0.15, 0.26].forEach((al, q) => { ctx.strokeStyle = `rgba(${c[0]},${c[1]},${c[2]},${Math.min(1, al * br)})`; ctx.stroke(buckets[q]); });
      const nb = [new Path2D(), new Path2D(), new Path2D(), new Path2D()], sz = this.dpr * this.sizeK;
      for (let i = 0; i < g.N; i++) {
        const p = P[i];
        if (!p) continue;
        const q = p[3] < 0.25 ? 0 : p[3] < 0.5 ? 1 : p[3] < 0.75 ? 2 : 3, s = (0.8 + 1.7 * p[3] * p[3]) * sz * (3.2 / p[2]);
        nb[q].rect(p[0] - s / 2, p[1] - s / 2, s, s);
      }
      [0.28, 0.45, 0.7, 1].forEach((al, q) => { ctx.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},${Math.min(1, al * br)})`; ctx.fill(nb[q]); });
      ctx.fillStyle = `rgba(${Math.round(c[0] + (255 - c[0]) * 0.8)},${Math.round(c[1] + (255 - c[1]) * 0.8)},${Math.round(c[2] + (255 - c[2]) * 0.8)},0.95)`;
      for (const q of this.pulses) {
        const a = P[q.a], b = P[q.b];
        if (!a || !b) continue;
        ctx.beginPath(); ctx.arc(a[0] + (b[0] - a[0]) * q.t, a[1] + (b[1] - a[1]) * q.t, (1.3 + 1.4 * a[3]) * sz, 0, 6.283); ctx.fill();
      }
    }
  }

  function createSphere(canvas, opts) {
    opts = opts || {};
    let core;
    const forced2d = /[?&]renderer=2d/.test(global.location.search);
    try {
      if (forced2d) throw new Error('rendu 2D demandé');
      core = new GLSphere(canvas, opts);
    } catch (err) {
      console.warn('Sphère : repli sur le rendu 2D (' + err.message + ')');
      const fresh = canvas.cloneNode(false);
      canvas.parentNode.replaceChild(fresh, canvas);
      core = new CanvasSphere(fresh, opts);
    }
    core.setDensity(opts.density || 1400);
    core.start();
    return core;
  }

  global.createSphere = createSphere;
})(window);
