/**
 * soul.js — 陪伴模式中心「灵体」(WebGL，有机质感 + 声纹反馈)
 * 四人格各自元素：天光 / 流焰 / 缓潮 / 墨。FBM 噪声肌理，非塑料。
 * window.Soul: setPersona(id) · setAudio(v) · startMicReactive() / stopMic()
 */
(function () {
  const PERSONA = {
    xi:       { mode: 0, col: [0.94, 0.78, 0.42], col2: [0.72, 0.53, 0.10] },
  };
  const VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';

  /* ─── Fragment Shader：氤氲光雾版 ───────────────────────────────────────
     核心思路：打碎"实心球感"——
     1. body 边界软化到 smoothstep(0.75, 0.0)，远端才归零
     2. body *= fbm 噪声调制 → 不规则云雾斑块，非均匀圆边
     3. mist1/mist2 两层外层雾气腱，rr 范围超出主体，形成向外飘散的氤氲
     4. alpha 由多层叠加而非单一 body，边缘半透而非硬截止
     5. 色调映射降分母(0.95)允许更多透明感，非塑料亮
  ─────────────────────────────────────────────────────────────────────── */
  const FS = `
precision highp float;
uniform vec2 u_res; uniform float u_time; uniform float u_mode;
uniform vec3 u_col; uniform vec3 u_col2; uniform float u_audio;

float hash(vec2 p){ p=fract(p*vec2(123.34,345.45)); p+=dot(p,p+34.345); return fract(p.x*p.y); }
float vn(vec2 p){
  vec2 i=floor(p),f=fract(p); f=f*f*(3.-2.*f);
  float a=hash(i),b=hash(i+vec2(1,0)),c=hash(i+vec2(0,1)),d=hash(i+vec2(1,1));
  return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
}
mat2 m2=mat2(1.6,1.2,-1.2,1.6);
float fbm(vec2 p){ float v=0.,a=.5; for(int i=0;i<6;i++){ v+=a*vn(p); p=m2*p; a*=.5; } return v; }

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*u_res) / u_res.y;
  float r   = length(uv);
  float ang = atan(uv.y, uv.x);
  float t   = u_time * 0.0006;

  vec2 p = uv * 2.7;
  vec2 q = vec2(fbm(p + t),              fbm(p + vec2(5.2, 1.3)));
  vec2 w = vec2(fbm(p + 2.3*q + vec2(1.7,9.2) + 0.5*t),
                fbm(p + 2.3*q + vec2(8.3,2.8) - 0.3*t));
  float f  = fbm(p + 2.3*w);
  float fb = fbm(p * 1.6 - t * 1.5);

  float aud   = u_audio;
  float voice = aud * (0.3 + 0.7 * fbm(vec2(ang*2.2 + u_time*0.02, r*3.0)));

  /* 扰动半径：增大噪声系数 (0.22→0.32) 让边缘更不规则 */
  float rr = r + (f - 0.5)*0.32 - voice*0.14;

  /* ── 墨人格（mode 3） ───────────────────────────── */
  if(u_mode > 2.5){
    float ink = smoothstep(0.46,0.16,rr)*(0.55+0.45*f);
    ink *= 0.68+0.32*fb; ink += aud*smoothstep(0.5,0.2,rr)*0.4;
    vec3 inkc = mix(vec3(0.40,0.41,0.43), vec3(0.06,0.07,0.09), clamp(f*1.35,0.,1.));
    gl_FragColor = vec4(inkc, clamp(ink,0.0,1.0)); return;
  }

  /* ── 氤氲主体 ────────────────────────────────────
     body: 软化到(0.75→0.0)，再乘 fbm 噪声打碎均匀圆圈
     → 云雾斑块感而非扎实球体                          */
  float noise_mask = 0.4 + 0.6 * fbm(p * 0.85 + t * 0.22);
  float body  = smoothstep(0.75, 0.0, rr) * noise_mask;
  float core  = pow(smoothstep(0.24, 0.0, rr), 2.2) * (1.3 + aud * 0.9);

  /* ── 外层雾气腱（mist）：延伸到球体外，形成氤氲飘散 ── */
  vec2 pp = uv * 1.55;
  float mist1 = fbm(pp + t*0.40 + q*0.85) * smoothstep(0.95, 0.08, rr);
  float mist2 = fbm(pp*1.25 - t*0.28 + w*0.90) * smoothstep(0.88, 0.0, rr);

  /* ── 色彩合成 ─────────────────────────────────────
     body 权重降至 0.42（减实感）；mist 层提供外层暖光  */
  vec3 base = mix(u_col2, u_col, clamp(f*1.4, 0., 1.));
  vec3 col = base   * body  * 0.42
           + u_col  * mist1 * 0.52
           + u_col  * mist2 * 0.38
           + vec3(1.0, 0.97, 0.92) * core * 0.88;

  /* ── 人格专属叠加 ──────────────────────────────── */
  if(u_mode < 0.5){
    /* xi 天光：金光丝缕 + 语音波纹 */
    float streak = fbm(vec2(ang*4.5 + f*3.0, r*3.5 - t*2.0));
    col += u_col * pow(streak, 1.6) * smoothstep(0.78, 0.04, r) * (0.42 + aud*0.35);
  } else if(u_mode < 1.5){
    /* yiyi 流焰 */
    float flame = fbm(p*2.2 + 1.6*q + vec2(0.0, -t*2.6));
    col += u_col * pow(flame, 1.7) * body * 0.55;
  } else {
    /* tianyuan 缓潮 */
    float rip = 0.5 + 0.5*sin(r*12.0 - t*13.0 + fb*3.5);
    col += vec3(0.5,0.82,1.0) * pow(rip,1.6) * body * (0.26 + aud*0.28);
  }

  /* 噪声颗粒感（保留，增加肌理） */
  col += (hash(uv*900.0 + u_time) - 0.5) * 0.028;

  /* 色调映射：分母提高至 0.95（允许更多透明质感，减饱和实感） */
  col = col / (col + vec3(0.95)) * 1.65;
  col = pow(clamp(col, 0., 1.), vec3(0.94));

  /* ── alpha 多层叠加：边缘渐隐而非硬截止 ── */
  float a = clamp(body*0.68 + mist1*0.58 + mist2*0.46 + core, 0.0, 1.0);
  gl_FragColor = vec4(col, a);
}`;

  let cv, gl, prog, uRes, uTime, uMode, uCol, uCol2, uAudio, DPR = Math.min(devicePixelRatio || 1, 2);
  let mode = 0, tMode = 0, col = PERSONA.xi.col.slice(), col2 = PERSONA.xi.col2.slice();
  let tCol = col.slice(), tCol2 = col2.slice(), audio = 0, tAudio = 0, ready = false, raf = 0;
  let analyser = null, audioCtx = null, micStream = null;

  function sh(ty, s) {
    const o = gl.createShader(ty); gl.shaderSource(o, s); gl.compileShader(o);
    if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) console.error('[soul]', gl.getShaderInfoLog(o));
    return o;
  }
  function init() {
    cv = document.getElementById('soulCanvas'); if (!cv) return false;
    gl = cv.getContext('webgl', { alpha: true, premultipliedAlpha: false, antialias: true });
    if (!gl) return false;
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error('[soul]', gl.getProgramInfoLog(prog)); return false; }
    gl.useProgram(prog);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,3,-1,-1,3]), gl.STATIC_DRAW);
    const l = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
    uRes  = gl.getUniformLocation(prog, 'u_res');
    uTime = gl.getUniformLocation(prog, 'u_time');
    uMode = gl.getUniformLocation(prog, 'u_mode');
    uCol  = gl.getUniformLocation(prog, 'u_col');
    uCol2 = gl.getUniformLocation(prog, 'u_col2');
    uAudio= gl.getUniformLocation(prog, 'u_audio');
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    resize(); addEventListener('resize', resize); ready = true;
    raf = requestAnimationFrame(loop); return true;
  }
  function resize() {
    const s = cv.clientWidth || 300;
    cv.width = s * DPR; cv.height = s * DPR;
    gl.viewport(0, 0, cv.width, cv.height);
  }
  function lerpArr(a, b, k) { for (let i = 0; i < 3; i++) a[i] += (b[i] - a[i]) * k; }
  function loop(ts) {
    if (!ready) return;
    if (analyser) {
      const d = new Uint8Array(analyser.frequencyBinCount); analyser.getByteFrequencyData(d);
      let s = 0; for (let i = 0; i < 24; i++) s += d[i]; tAudio = Math.min(1, (s/24)/140);
    }
    mode += (tMode - mode) * 0.12;
    lerpArr(col, tCol, 0.1); lerpArr(col2, tCol2, 0.1);
    audio += (tAudio - audio) * 0.2;
    if (document.body.classList.contains('mode-companion')) {
      const want = Math.round((cv.clientWidth || 300) * DPR);
      if (want > 0 && cv.width !== want) resize();
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(uRes, cv.width, cv.height);
      gl.uniform1f(uTime, ts || 0);
      gl.uniform1f(uMode, mode);
      gl.uniform3fv(uCol, col); gl.uniform3fv(uCol2, col2);
      gl.uniform1f(uAudio, audio);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    raf = requestAnimationFrame(loop);
  }

  const Soul = {
    setPersona(id) {
      const p = PERSONA[id]; if (!p) return;
      tMode = p.mode; tCol = p.col.slice(); tCol2 = p.col2.slice();
      if (!ready) { mode = p.mode; col = p.col.slice(); col2 = p.col2.slice(); }
    },
    setAudio(v) { tAudio = Math.max(0, Math.min(1, v)); },
    async startMicReactive() {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioCtx  = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtx.createMediaStreamSource(micStream);
        analyser  = audioCtx.createAnalyser(); analyser.fftSize = 128; src.connect(analyser);
        return true;
      } catch (e) { analyser = null; return false; }
    },
    stopMic() {
      tAudio = 0; if (analyser) analyser = null;
      if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
      if (audioCtx)  { try { audioCtx.close(); } catch (_) {} audioCtx = null; }
    },
  };
  window.Soul = Soul;
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
