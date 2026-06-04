/**
 * Anima — persona-fx.js
 * 全程沉浸：四人格 WebGL 世界，铺在聊天页背后。带开关（设置可关 / 低端机 / reduced-motion 自动关）。
 * 纯原生 WebGL，无库。window.PersonaFX 暴露 setMode / enable / isEnabled。
 */
(function () {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // agent tab → 世界模式： 神女=1 / 晞=0 / 陶朱=2 / 守藏=3
  const MODE = { xi: 1 };

  const VERT = `attribute vec2 p; void main(){ gl_Position=vec4(p,0.,1.); }`;
  const FRAG = `
precision highp float;
uniform vec2 u_res; uniform float u_time; uniform vec2 u_mouse; uniform float u_mode;
float hash(vec2 p){ p=fract(p*vec2(123.34,345.45)); p+=dot(p,p+34.345); return fract(p.x*p.y); }
float vnoise(vec2 p){ vec2 i=floor(p),f=fract(p); f=f*f*(3.0-2.0*f);
  float a=hash(i),b=hash(i+vec2(1,0)),c=hash(i+vec2(0,1)),d=hash(i+vec2(1,1));
  return mix(mix(a,b,f.x),mix(c,d,f.x),f.y); }
mat2 m2=mat2(1.6,1.2,-1.2,1.6);
float fbm(vec2 p){ float v=0.0,a=0.5; for(int i=0;i<6;i++){ v+=a*vnoise(p); p=m2*p; a*=0.5; } return v; }
float mountain(float x,float seed,float amp){ return amp*fbm(vec2(x*1.3+seed,seed))+amp*0.4*fbm(vec2(x*3.1+seed,seed)); }
float stars(vec2 uv,float density,float sz){
  vec2 g=uv*density; vec2 id=floor(g); vec2 f=fract(g)-0.5;
  float h=hash(id); if(h<0.96) return 0.0;
  float d=length(f-(vec2(hash(id+1.0),hash(id+2.0))-0.5)*0.6);
  float tw=0.5+0.5*sin(u_time*2.0*(0.5+h)*6.28+h*50.0);
  return smoothstep(sz,0.0,d)*tw; }
void main(){
  vec2 uv=(gl_FragCoord.xy-0.5*u_res)/u_res.y;
  vec2 mo=u_mouse*0.12; float t=u_time*0.05; vec3 col=vec3(0.0);
  vec2 pp=uv*1.7+mo;
  vec2 q=vec2(fbm(pp+t), fbm(pp+vec2(5.2,1.3)));
  vec2 r=vec2(fbm(pp+3.0*q+vec2(1.7,9.2)+t*0.6), fbm(pp+3.0*q+vec2(8.3,2.8)-t*0.4));
  float f=fbm(pp+3.0*r);
  if(u_mode<0.5){
    float band=smoothstep(0.66,0.0, abs(uv.y-uv.x*0.5+0.05));
    col=vec3(0.018,0.012,0.045);
    col=mix(col, vec3(0.17,0.05,0.33), f*1.3);
    col=mix(col, vec3(0.46,0.12,0.56), clamp(length(r)*0.9,0.,1.)*band);
    col=mix(col, vec3(0.08,0.15,0.44), clamp(q.x*0.7,0.,1.));
    col+=vec3(0.75,0.55,1.0)*pow(f,4.0)*(0.35+band*0.9);
    float st=stars(uv+mo*0.4,72.0,0.020)+stars(uv+mo*0.8,150.0,0.012)*0.7+stars(uv+mo*1.4,300.0,0.007)*0.45;
    col+=vec3(0.92,0.94,1.0)*st*(0.55+band*0.9);
  } else if(u_mode<1.5){
    float sky=clamp(uv.y*0.6+0.5,0.0,1.0);
    col=mix(vec3(0.86,0.61,0.26), vec3(1.0,0.99,0.94), sky*sky);
    col=mix(col, vec3(1.0,0.93,0.74), smoothstep(0.28,0.82,f)*0.7);
    col+=vec3(0.5,0.34,0.12)*pow(f,2.0)*0.35;
    vec2 d=uv-vec2(mo.x*0.3,0.94); float dist=length(d); float ang=atan(d.x,-d.y);
    float rays=pow(0.5+0.5*sin(ang*18.0+f*4.0+sin(u_time*0.1)),4.0);
    float fall=clamp(1.0-dist*0.5,0.0,1.0);
    col+=vec3(1.0,0.96,0.80)*rays*fall*0.5;
    col+=vec3(1.0,0.98,0.90)*pow(fall,4.0)*0.95;
    col+=vec3(1.0,0.88,0.5)*pow(f,7.0)*0.6;
  } else if(u_mode<2.5){
    float hz=0.15;
    if(uv.y>hz){
      float s=(uv.y-hz)/(1.0-hz);
      col=mix(vec3(0.10,0.32,0.44), vec3(0.02,0.09,0.20), s);
      col+=vec3(0.06,0.10,0.16)*f*0.6;
      col+=vec3(0.85,0.96,1.0)*pow(clamp(1.0-length(uv-vec2(0.0,0.55))*3.2,0.,1.),2.0)*0.8;
    } else {
      vec2 wp=vec2(uv.x*1.5+t*0.8, (hz-uv.y)*3.2);
      vec2 wq=vec2(fbm(wp), fbm(wp+vec2(3.0,1.0)));
      float wf=fbm(wp+2.2*wq); float dd=hz-uv.y;
      col=mix(vec3(0.06,0.30,0.42), vec3(0.004,0.05,0.12), clamp(dd*1.3,0.,1.0));
      col+=vec3(0.10,0.44,0.54)*wf*0.7;
      col+=vec3(0.5,0.86,1.0)*pow(wf,3.0)*clamp(1.0-dd,0.,1.0)*0.55;
      float glint=pow(clamp(1.0-abs(uv.x)*4.0,0.,1.0),2.0);
      col+=vec3(0.8,0.95,1.0)*glint*pow(wf,2.0)*clamp(1.0-dd*1.5,0.,1.0)*0.9;
    }
    col+=vec3(0.85,0.97,1.0)*pow(clamp(1.0-abs(uv.y-hz)*44.0,0.,1.0),1.5)*0.22;
  } else if(u_mode<3.5){
    vec3 paper=mix(vec3(0.915,0.895,0.825), vec3(0.965,0.952,0.905), uv.y*0.5+0.5);
    col=paper; float x=uv.x+mo.x*0.12;
    float h0=0.34+mountain(x*0.9,7.0,0.055);
    col=mix(col, vec3(0.68,0.69,0.68), smoothstep(0.035,-0.03,uv.y-h0)*0.26);
    float h1=0.18+mountain(x,17.0,0.10); float ink1=0.5+0.4*fbm(pp*1.3+vec2(17.0,0.0));
    col=mix(col, mix(vec3(0.60,0.61,0.61),vec3(0.45,0.46,0.47),ink1), smoothstep(0.04,-0.03,uv.y-h1)*0.5);
    float h2=0.0+mountain(x,33.0,0.15); float ink2=0.45+0.5*fbm(pp*1.7+vec2(33.0,0.0));
    col=mix(col, mix(vec3(0.40,0.41,0.43),vec3(0.25,0.26,0.29),ink2), smoothstep(0.045,-0.035,uv.y-h2)*0.72);
    float h3=-0.30+mountain(x*0.8,57.0,0.20); float ink3=0.4+0.55*fbm(pp*2.1+vec2(57.0,0.0));
    float nm=smoothstep(0.055,-0.06,uv.y-h3);
    col=mix(col, mix(vec3(0.17,0.18,0.21),vec3(0.05,0.06,0.08),ink3), nm);
    col=mix(col, vec3(0.03,0.04,0.06), smoothstep(0.0,0.045,uv.y-h3)*smoothstep(0.055,0.0,uv.y-h3)*0.6);
    float mist=smoothstep(0.16,0.0,abs(uv.y-0.07))*(0.5+0.5*fbm(vec2(uv.x*2.2+t*0.25,1.0)));
    mist+=smoothstep(0.13,0.0,abs(uv.y+0.17))*(0.45+0.5*fbm(vec2(uv.x*2.0-t*0.2,4.0)));
    col=mix(col, paper, clamp(mist,0.0,0.9)*0.62);
  } else {
    // Anima 本相：暖白柔雾（贴合米白身份，托白色/玻璃面板不割裂）
    vec3 a=mix(vec3(0.965,0.955,0.92), vec3(0.915,0.895,0.83), clamp(uv.y*0.5+0.5,0.0,1.0));
    a=mix(a, vec3(0.90,0.86,0.76), f*0.22);                          // 柔雾暖纹
    a=mix(a, vec3(0.90,0.915,0.93), clamp(length(r)*0.25,0.0,1.0));  // 一丝冷调平衡
    a+=vec3(0.05,0.045,0.03)*pow(clamp(f,0.0,1.0),4.0);              // 微暖光斑
    col=a;
  }
  float vig = (u_mode>2.5) ? (1.0-0.14*dot(uv,uv)) : (1.0-0.34*dot(uv,uv));
  col*=vig; col+=(hash(uv*1000.0+u_time)-0.5)*0.025;
  if(u_mode<2.5){ col=col/(col+vec3(0.9))*1.9; col=pow(clamp(col,0.0,1.0),vec3(0.95)); }
  gl_FragColor=vec4(clamp(col,0.0,1.0),1.0);
}`;

  let cv, gl, prog, uRes, uTime, uMouse, uMode;
  let W, H, DPR = Math.min(devicePixelRatio || 1, 2);
  let mouse = { x: 0, y: 0, tx: 0, ty: 0 };
  let mode = 4, targetMode = 4, raf = 0, enabled = false, running = false;

  function compile(type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error('[fx] shader', gl.getShaderInfoLog(s));
    return s;
  }
  function initGL() {
    cv = document.getElementById('persona-fx');
    if (!cv) return false;
    gl = cv.getContext('webgl', { antialias: true, alpha: false, powerPreference: 'high-performance' })
      || cv.getContext('experimental-webgl');
    if (!gl) return false;
    const vs = compile(gl.VERTEX_SHADER, VERT), fs = compile(gl.FRAGMENT_SHADER, FRAG);
    prog = gl.createProgram(); gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error('[fx] link', gl.getProgramInfoLog(prog)); return false; }
    gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    uRes = gl.getUniformLocation(prog, 'u_res'); uTime = gl.getUniformLocation(prog, 'u_time');
    uMouse = gl.getUniformLocation(prog, 'u_mouse'); uMode = gl.getUniformLocation(prog, 'u_mode');
    return true;
  }
  function resize() {
    W = innerWidth; H = innerHeight;
    cv.width = W * DPR; cv.height = H * DPR; cv.style.width = W + 'px'; cv.style.height = H + 'px';
    gl && gl.viewport(0, 0, cv.width, cv.height);
  }
  function frame(ts) {
    if (!running) return;
    mouse.x += (mouse.tx - mouse.x) * 0.05; mouse.y += (mouse.ty - mouse.y) * 0.05;
    // mode 平滑切换
    mode += (targetMode - mode) * 0.14; if (Math.abs(targetMode - mode) < 0.01) mode = targetMode;
    gl.uniform2f(uRes, cv.width, cv.height); gl.uniform1f(uTime, (ts || 0) * 0.001);
    gl.uniform2f(uMouse, mouse.x, mouse.y); gl.uniform1f(uMode, mode);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = requestAnimationFrame(frame);
  }
  function start() { if (!running && enabled && gl) { running = true; raf = requestAnimationFrame(frame); } }
  function stop() { running = false; cancelAnimationFrame(raf); }

  const PersonaFX = {
    _ready: false,
    init() {
      if (this._ready) return;
      if (!initGL()) { document.body.classList.remove('fx-on'); return; }
      resize(); addEventListener('resize', resize);
      addEventListener('pointermove', e => { mouse.tx = (e.clientX / innerWidth) * 2 - 1; mouse.ty = -((e.clientY / innerHeight) * 2 - 1); });
      document.addEventListener('visibilitychange', () => document.hidden ? stop() : (enabled && start()));
      this._ready = true;
      // 读取持久化开关（reduced-motion 默认关）
      const saved = localStorage.getItem('anima_fx');
      this.enable(saved ? saved === 'on' : !reduce, true);
      this.setMode(document.body.dataset.agent || 'overview');  // 首屏即铺环境本相
    },
    setMode(tab) {
      // 人格页 → 各自世界；其余页 → 环境本相(4)。全程有世界，治割裂。
      targetMode = (MODE[tab] !== undefined) ? MODE[tab] : 4;
      if (!running) mode = targetMode;           // 首次/重启直接定位
      if (enabled) { document.body.classList.add('fx-show'); start(); }
    },
    enable(on, silent) {
      enabled = !!on;
      document.body.classList.toggle('fx-on', enabled);
      if (!silent) localStorage.setItem('anima_fx', enabled ? 'on' : 'off');
      if (!enabled) { stop(); document.body.classList.remove('fx-show'); }
      else { document.body.classList.add('fx-show'); start(); }
      const t = document.getElementById('fxToggle'); if (t) t.classList.toggle('on', enabled);
    },
    toggle() { this.enable(!enabled); },
    isEnabled() { return enabled; },
  };
  window.PersonaFX = PersonaFX;
  if (document.readyState !== 'loading') PersonaFX.init();
  else document.addEventListener('DOMContentLoaded', () => PersonaFX.init());
})();
