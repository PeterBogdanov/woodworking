/* BoardcamViewer — 3-D просмотрщик на чистом WebGL1, без зависимостей.
 * Единицы — мм, Z вверх, Z=0 — верх детали. Слои: stl, machined, blank, origin.
 * window.BoardcamViewer(canvas) -> { loadStl, loadHeightmap, setBlank, setLayerVisible, fit, clear }
 */
(function () {
'use strict';

var VS = [
  'attribute vec3 aPos; attribute vec3 aNormal; attribute vec3 aColor;',
  'uniform mat4 uProj; uniform mat4 uView;',
  'varying vec3 vNormal; varying vec3 vColor;',
  'void main() { gl_Position = uProj * uView * vec4(aPos, 1.0); vNormal = aNormal; vColor = aColor; }'
].join('\n');
var FS = [
  'precision mediump float;',
  'uniform float uLit; uniform vec3 uLightDir;',
  'varying vec3 vNormal; varying vec3 vColor;',
  'void main() {',
  '  float k = 1.0;',
  '  if (uLit > 0.5) {',
  '    vec3 n = normalize(vNormal);',
  '    float d = abs(dot(n, normalize(uLightDir)));',   // двустороннее освещение
  '    k = 0.35 + 0.65 * d;',
  '  }',
  '  gl_FragColor = vec4(vColor * k, 1.0);',
  '}'
].join('\n');

/* ---------- векторная математика ---------- */
function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function norm(a) { var l = Math.sqrt(dot(a, a)); return l > 0 ? [a[0] / l, a[1] / l, a[2] / l] : [0, 0, 1]; }

function perspective(fovy, aspect, near, far) {
  var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
}
function lookAt(eye, center, up) {
  var f = norm(sub(center, eye)), s = norm(cross(f, up)), u = cross(s, f);
  return new Float32Array([
    s[0], u[0], -f[0], 0,
    s[1], u[1], -f[1], 0,
    s[2], u[2], -f[2], 0,
    -dot(s, eye), -dot(u, eye), dot(f, eye), 1]);
}

/* ---------- разбор STL ---------- */
function parseStl(buf) {
  var bytes = new Uint8Array(buf);
  var isBinary = false;
  if (buf.byteLength >= 84) {
    var n = new DataView(buf).getUint32(80, true);
    if (84 + n * 50 === buf.byteLength) isBinary = true;
  }
  if (!isBinary) {
    var head = '';
    for (var k = 0; k < Math.min(bytes.length, 80); k++) head += String.fromCharCode(bytes[k]);
    if (head.trim().toLowerCase().indexOf('solid') === 0) return parseAsciiStl(buf);
    if (buf.byteLength < 84) throw new Error('STL: файл слишком короткий');
    isBinary = true; // размер не сошёлся, но это не текст — читаем сколько есть
  }
  var dv = new DataView(buf);
  var count = Math.min(dv.getUint32(80, true), Math.floor((buf.byteLength - 84) / 50));
  var pos = new Float32Array(count * 9);
  var off = 84;
  for (var t = 0; t < count; t++) {
    off += 12; // нормаль из файла игнорируем, считаем сами
    for (var v = 0; v < 9; v++) { pos[t * 9 + v] = dv.getFloat32(off, true); off += 4; }
    off += 2;
  }
  return pos;
}
function parseAsciiStl(buf) {
  if (typeof TextDecoder === 'undefined') throw new Error('STL ASCII: нет TextDecoder');
  var text = new TextDecoder('utf-8').decode(buf);
  var re = /vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/g, m, arr = [];
  while ((m = re.exec(text))) arr.push(+m[1], +m[2], +m[3]);
  var tri = Math.floor(arr.length / 9);
  return new Float32Array(arr.slice(0, tri * 9));
}
function faceNormals(pos) {
  var nrm = new Float32Array(pos.length);
  for (var i = 0; i < pos.length; i += 9) {
    var a = [pos[i], pos[i + 1], pos[i + 2]], b = [pos[i + 3], pos[i + 4], pos[i + 5]], c = [pos[i + 6], pos[i + 7], pos[i + 8]];
    var n = norm(cross(sub(b, a), sub(c, a)));
    for (var v = 0; v < 3; v++) { nrm[i + v * 3] = n[0]; nrm[i + v * 3 + 1] = n[1]; nrm[i + v * 3 + 2] = n[2]; }
  }
  return nrm;
}
function boundsOf(pos, stride, count) {
  var mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (var i = 0; i < count; i++) {
    for (var k = 0; k < 3; k++) {
      var v = pos[i * stride + k];
      if (v < mn[k]) mn[k] = v;
      if (v > mx[k]) mx[k] = v;
    }
  }
  return isFinite(mn[0]) ? { min: mn, max: mx } : null;
}

/* ---------- карта высот BCHM ---------- */
function parseHeightmap(buf) {
  if (buf.byteLength < 24) throw new Error('Heightmap: файл слишком короткий');
  var dv = new DataView(buf);
  var magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'BCHM') throw new Error('Heightmap: неверная сигнатура "' + magic + '"');
  var nx = dv.getUint32(4, true), ny = dv.getUint32(8, true);
  var pitch = dv.getFloat32(12, true), x0 = dv.getFloat32(16, true), y0 = dv.getFloat32(20, true);
  if (buf.byteLength < 24 + nx * ny * 4) throw new Error('Heightmap: файл обрезан');
  var z = new Float32Array(buf, 24, nx * ny);
  return { nx: nx, ny: ny, pitch: pitch, x0: x0, y0: y0, z: z };
}
var WOOD_LIGHT = [0.87, 0.76, 0.58], WOOD_DARK = [0.63, 0.33, 0.10];
function buildHeightmapMesh(hm) {
  var nx = hm.nx, ny = hm.ny, z = hm.z, N = nx * ny;
  var valid = new Uint8Array(N), minZ = 0;
  for (var k = 0; k < N; k++) { if (z[k] > -1e8) { valid[k] = 1; if (z[k] < minZ) minZ = z[k]; } }
  var maxDepth = Math.max(0.001, -minZ);
  var pos = new Float32Array(N * 3), nrm = new Float32Array(N * 3), col = new Float32Array(N * 3);
  for (var j = 0; j < ny; j++) {
    for (var i = 0; i < nx; i++) {
      var idx = j * nx + i, o = idx * 3;
      pos[o] = hm.x0 + (i + 0.5) * hm.pitch;
      pos[o + 1] = hm.y0 + (j + 0.5) * hm.pitch;
      pos[o + 2] = valid[idx] ? z[idx] : 0;
      var t = valid[idx] ? Math.min(1, Math.max(0, -z[idx] / maxDepth)) : 0;
      col[o] = WOOD_LIGHT[0] + (WOOD_DARK[0] - WOOD_LIGHT[0]) * t;
      col[o + 1] = WOOD_LIGHT[1] + (WOOD_DARK[1] - WOOD_LIGHT[1]) * t;
      col[o + 2] = WOOD_LIGHT[2] + (WOOD_DARK[2] - WOOD_LIGHT[2]) * t;
    }
  }
  var idxs = [];
  function tri(a, b, c) {
    idxs.push(a, b, c);
    var A = [pos[a * 3], pos[a * 3 + 1], pos[a * 3 + 2]], B = [pos[b * 3], pos[b * 3 + 1], pos[b * 3 + 2]], C = [pos[c * 3], pos[c * 3 + 1], pos[c * 3 + 2]];
    var n = cross(sub(B, A), sub(C, A));
    [a, b, c].forEach(function (v) { nrm[v * 3] += n[0]; nrm[v * 3 + 1] += n[1]; nrm[v * 3 + 2] += n[2]; });
  }
  for (var jj = 0; jj < ny - 1; jj++) {
    for (var ii = 0; ii < nx - 1; ii++) {
      var a = jj * nx + ii, b = a + 1, c = a + nx, d = c + 1;
      var va = valid[a], vb = valid[b], vc = valid[c], vd = valid[d];
      if (va && vb && vc && vd) { tri(a, b, d); tri(a, d, c); }
      else if (va && vb && vd) tri(a, b, d);
      else if (va && vd && vc) tri(a, d, c);
      else if (va && vb && vc) tri(a, b, c);
      else if (vb && vd && vc) tri(b, d, c);
    }
  }
  for (var v = 0; v < N; v++) {
    var n2 = norm([nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]]);
    nrm[v * 3] = n2[0]; nrm[v * 3 + 1] = n2[1]; nrm[v * 3 + 2] = n2[2];
  }
  return { pos: pos, nrm: nrm, col: col, idx: idxs, validCount: N };
}
/* Разворачивает индексированную сетку в плоский список вершин (если нет OES_element_index_uint). */
function expandIndexed(m) {
  var n = m.idx.length, pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), col = new Float32Array(n * 3);
  for (var i = 0; i < n; i++) {
    var v = m.idx[i];
    for (var k = 0; k < 3; k++) { pos[i * 3 + k] = m.pos[v * 3 + k]; nrm[i * 3 + k] = m.nrm[v * 3 + k]; col[i * 3 + k] = m.col[v * 3 + k]; }
  }
  return { pos: pos, nrm: nrm, col: col, idx: null };
}

/* ---------- сам просмотрщик ---------- */
function BoardcamViewer(canvas) {
  var gl = canvas.getContext('webgl', { antialias: true }) || canvas.getContext('experimental-webgl');
  if (!gl) throw new Error('WebGL недоступен в этом браузере');
  var extUint = gl.getExtension('OES_element_index_uint');

  function compile(type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error('Шейдер: ' + gl.getShaderInfoLog(sh));
    return sh;
  }
  var prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('Программа: ' + gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  var loc = {
    aPos: gl.getAttribLocation(prog, 'aPos'), aNormal: gl.getAttribLocation(prog, 'aNormal'), aColor: gl.getAttribLocation(prog, 'aColor'),
    uProj: gl.getUniformLocation(prog, 'uProj'), uView: gl.getUniformLocation(prog, 'uView'),
    uLit: gl.getUniformLocation(prog, 'uLit'), uLightDir: gl.getUniformLocation(prog, 'uLightDir')
  };
  gl.enable(gl.DEPTH_TEST);

  // слои: mesh = {vbo, nbo, cbo, ibo, count, indexType, mode, bounds}
  var layers = {
    stl: { mesh: null, visible: true, color: [0.847, 0.725, 0.541], lit: true },
    machined: { mesh: null, visible: true, color: [1, 1, 1], lit: true },
    blank: { mesh: null, visible: true, color: [0.55, 0.55, 0.58], lit: false },
    origin: { mesh: null, visible: true, color: [0.9, 0.15, 0.15], lit: false }
  };
  var cam = { target: [0, 0, 0], dist: 400, az: -0.8, el: 0.55, fov: Math.PI / 5 };
  var sceneRadius = 100;

  function makeBuffer(target, data) {
    var b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, data, gl.STATIC_DRAW); return b;
  }
  function makeMesh(pos, nrm, col, idx, mode) {
    var m = { vbo: makeBuffer(gl.ARRAY_BUFFER, pos), nbo: nrm ? makeBuffer(gl.ARRAY_BUFFER, nrm) : null,
      cbo: col ? makeBuffer(gl.ARRAY_BUFFER, col) : null, ibo: null, indexType: 0, mode: mode, count: pos.length / 3,
      bounds: boundsOf(pos, 3, pos.length / 3) };
    if (idx) {
      var arr = idx instanceof Uint32Array ? idx : new Uint32Array(idx);
      if (pos.length / 3 <= 65535) { arr = new Uint16Array(arr); m.indexType = gl.UNSIGNED_SHORT; }
      else m.indexType = gl.UNSIGNED_INT;
      m.ibo = makeBuffer(gl.ELEMENT_ARRAY_BUFFER, arr);
      m.count = arr.length;
    }
    return m;
  }
  function freeMesh(m) {
    if (!m) return;
    [m.vbo, m.nbo, m.cbo, m.ibo].forEach(function (b) { if (b) gl.deleteBuffer(b); });
  }
  function setLayerMesh(name, mesh) {
    freeMesh(layers[name].mesh); layers[name].mesh = mesh;
  }

  function drawLayer(L) {
    var m = L.mesh;
    if (!m || !L.visible) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, m.vbo);
    gl.enableVertexAttribArray(loc.aPos); gl.vertexAttribPointer(loc.aPos, 3, gl.FLOAT, false, 0, 0);
    if (m.nbo) { gl.bindBuffer(gl.ARRAY_BUFFER, m.nbo); gl.enableVertexAttribArray(loc.aNormal); gl.vertexAttribPointer(loc.aNormal, 3, gl.FLOAT, false, 0, 0); }
    else { gl.disableVertexAttribArray(loc.aNormal); gl.vertexAttrib3f(loc.aNormal, 0, 0, 1); }
    if (m.cbo) { gl.bindBuffer(gl.ARRAY_BUFFER, m.cbo); gl.enableVertexAttribArray(loc.aColor); gl.vertexAttribPointer(loc.aColor, 3, gl.FLOAT, false, 0, 0); }
    else { gl.disableVertexAttribArray(loc.aColor); gl.vertexAttrib3f(loc.aColor, L.color[0], L.color[1], L.color[2]); }
    gl.uniform1f(loc.uLit, L.lit ? 1 : 0);
    if (m.ibo) { gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, m.ibo); gl.drawElements(m.mode, m.count, m.indexType, 0); }
    else gl.drawArrays(m.mode, 0, m.count);
  }

  function resize() {
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
  }
  function eyeVec() {
    var ce = Math.cos(cam.el);
    return [Math.cos(cam.az) * ce, Math.sin(cam.az) * ce, Math.sin(cam.el)];
  }
  function render() {
    pending = false;
    resize();
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    var e = eyeVec();
    var eye = [cam.target[0] + e[0] * cam.dist, cam.target[1] + e[1] * cam.dist, cam.target[2] + e[2] * cam.dist];
    var near = Math.max(0.05, cam.dist - sceneRadius * 3), far = cam.dist + sceneRadius * 3;
    gl.uniformMatrix4fv(loc.uProj, false, perspective(cam.fov, canvas.width / canvas.height, near, far));
    gl.uniformMatrix4fv(loc.uView, false, lookAt(eye, cam.target, [0, 0, 1]));
    var l = norm([e[0] + 0.3, e[1] - 0.2, e[2] + 0.6]); // свет чуть сбоку и сверху от камеры
    gl.uniform3f(loc.uLightDir, l[0], l[1], l[2]);
    drawLayer(layers.stl);
    drawLayer(layers.machined);
    drawLayer(layers.blank);
    drawLayer(layers.origin);
  }
  var pending = false;
  function requestRender() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(render);
  }

  function fit() {
    var mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity], any = false;
    Object.keys(layers).forEach(function (k) {
      var L = layers[k];
      if (!L.mesh || !L.mesh.bounds || !L.visible) return;
      any = true;
      for (var i = 0; i < 3; i++) { mn[i] = Math.min(mn[i], L.mesh.bounds.min[i]); mx[i] = Math.max(mx[i], L.mesh.bounds.max[i]); }
    });
    if (!any) { requestRender(); return; }
    cam.target = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
    var d = sub(mx, mn);
    sceneRadius = Math.max(1, Math.sqrt(dot(d, d)) / 2);
    cam.dist = sceneRadius / Math.sin(cam.fov / 2) * 1.1;
    requestRender();
  }

  /* --- управление: ЛКМ — орбита, колесо — масштаб, ПКМ/Shift+ЛКМ — сдвиг --- */
  var drag = null;
  canvas.addEventListener('contextmenu', function (e) { e.preventDefault(); });
  canvas.addEventListener('pointerdown', function (e) {
    if (e.button !== 0 && e.button !== 2) return;
    drag = { x: e.clientX, y: e.clientY, mode: (e.button === 2 || e.shiftKey) ? 'pan' : 'orbit' };
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* не критично */ }
    e.preventDefault();
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.mode === 'orbit') {
      cam.az -= dx * 0.01;
      cam.el = Math.max(-1.5, Math.min(1.5, cam.el + dy * 0.01));
    } else {
      var f = norm(sub([0, 0, 0], eyeVec()));            // направление взгляда
      var right = norm(cross(f, [0, 0, 1])), up = cross(right, f);
      var s = 2 * Math.tan(cam.fov / 2) * cam.dist / Math.max(1, canvas.clientHeight); // мм на пиксель у цели
      for (var i = 0; i < 3; i++) cam.target[i] += (-right[i] * dx + up[i] * dy) * s;
    }
    requestRender();
  });
  function endDrag(e) { if (drag) { drag = null; try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* ok */ } } }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('wheel', function (e) {
    e.preventDefault();
    cam.dist = Math.max(sceneRadius * 0.05, Math.min(sceneRadius * 50, cam.dist * Math.exp(e.deltaY * 0.0015)));
    requestRender();
  }, { passive: false });
  canvas.addEventListener('dblclick', function () { fit(); });
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { requestRender(); }).observe(canvas);
  else window.addEventListener('resize', requestRender);

  /* --- публичный API --- */
  var api = {
    loadStl: function (arrayBuffer) {
      var pos = parseStl(arrayBuffer);
      if (!pos.length) throw new Error('STL: нет треугольников');
      setLayerMesh('stl', makeMesh(pos, faceNormals(pos), null, null, gl.TRIANGLES));
      fit();
      return pos.length / 9;
    },
    loadHeightmap: function (arrayBuffer) {
      var hm = parseHeightmap(arrayBuffer);
      var m = buildHeightmapMesh(hm);
      if (!m.idx.length) throw new Error('Heightmap: нет данных');
      if (!extUint && m.validCount > 65535) m = expandIndexed(m);
      setLayerMesh('machined', makeMesh(m.pos, m.nrm, m.col, m.idx, gl.TRIANGLES));
      fit();
      return { nx: hm.nx, ny: hm.ny, pitch: hm.pitch };
    },
    setBlank: function (sx, sy, thick) {
      var hx = sx / 2, hy = sy / 2, z0 = -thick, z1 = 0;
      var c = [[-hx, -hy, z0], [hx, -hy, z0], [hx, hy, z0], [-hx, hy, z0], [-hx, -hy, z1], [hx, -hy, z1], [hx, hy, z1], [-hx, hy, z1]];
      var edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
      var pos = new Float32Array(edges.length * 6);
      edges.forEach(function (e, i) { for (var k = 0; k < 3; k++) { pos[i * 6 + k] = c[e[0]][k]; pos[i * 6 + 3 + k] = c[e[1]][k]; } });
      setLayerMesh('blank', makeMesh(pos, null, null, null, gl.LINES));
      // маркер нуля X0Y0 — красный крестик в углу (-sx/2, -sy/2, 0)
      var L = Math.max(3, Math.min(sx, sy) * 0.03), ox = -hx, oy = -hy;
      var cr = new Float32Array([ox - L, oy, 0, ox + L, oy, 0, ox, oy - L, 0, ox, oy + L, 0, ox, oy, -L, ox, oy, L]);
      setLayerMesh('origin', makeMesh(cr, null, null, null, gl.LINES));
      fit();
    },
    setLayerVisible: function (name, on) {
      if (layers[name]) { layers[name].visible = !!on; requestRender(); }
    },
    fit: fit,
    clear: function () {
      Object.keys(layers).forEach(function (k) { setLayerMesh(k, null); });
      requestRender();
    },
    render: requestRender
  };
  requestRender();
  return api;
}

window.BoardcamViewer = BoardcamViewer;
})();
