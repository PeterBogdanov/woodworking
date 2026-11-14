/* CamStudio UI — интерактивный 3D просмотрщик и клиент CAM генератора */
(function () {
  'use strict';

  var state = {
    toolpaths: [],
    stock: { width: 300, height: 200, thickness: 22 },
    rotX: 55,
    rotZ: -35,
    zoom: 1.6,
    panX: 0,
    panY: 0,
    isDragging: false,
    dragStart: { x: 0, y: 0 }
  };

  function $(id) { return document.getElementById(id); }

  // 1. Интерактивный калькулятор режимов резания
  async function updateChipLoad() {
    var payload = {
      dia: parseFloat($('tool-dia').value) || 6.35,
      flutes: parseInt($('tool-flutes').value) || 2,
      rpm: parseInt($('tool-rpm').value) || 18000,
      stepdown: parseFloat($('tool-stepdown').value) || 3.5,
      material: $('stock-material').value
    };

    try {
      var res = await fetch('/api/chipload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      
      $('res-chipload').textContent = data.chip_load_mm_tooth + ' мм/зуб';
      $('res-feed').textContent = data.feed_mm_min + ' мм/мин';
      $('res-makita').textContent = 'Колесико ~' + data.makita_dial + ' (' + Math.round(data.rpm/1000) + 'k)';

      var riskEl = $('res-risk');
      if (data.burn_risk) {
        riskEl.className = 'status-warn';
        riskEl.textContent = 'ВНИМАНИЕ: Слишком высокая частота при низкой подаче — риск прижога!';
      } else if (data.overload_risk) {
        riskEl.className = 'status-warn';
        riskEl.textContent = 'ВНИМАНИЕ: Слишком большая нагрузка на зуб фрезы!';
      } else {
        riskEl.className = 'status-ok';
        riskEl.textContent = 'Обороты и подача сбалансированы (чистый рез без прижога)';
      }
    } catch (e) {
      console.error('Ошибка расчета chipload:', e);
    }
  }

  // 2. Поворот стрелки направления волокон
  function updateGrainVisual() {
    var deg = $('grain-angle').value;
    $('grain-deg-display').textContent = deg + '°';
    $('grain-arrow').style.transform = 'rotate(' + deg + 'deg)';
  }

  // 3. Генерация G-кода
  async function generateGcode() {
    var btn = $('btn-generate');
    btn.disabled = true;
    btn.textContent = 'Расчет траекторий...';

    var payload = {
      stock: {
        width: parseFloat($('stock-w').value) || 300,
        height: parseFloat($('stock-h').value) || 200,
        thickness: parseFloat($('stock-thick').value) || 22,
        material: $('stock-material').value
      },
      tool: {
        dia: parseFloat($('tool-dia').value) || 6.35,
        flutes: parseInt($('tool-flutes').value) || 2,
        rpm: parseInt($('tool-rpm').value) || 18000,
        stepdown: parseFloat($('tool-stepdown').value) || 3.5
      },
      grain_angle: parseFloat($('grain-angle').value) || 0,
      climb_only: $('opt-climb').checked,
      helical_ramp: $('opt-helical').checked,
      use_3d_tabs: $('opt-3dtabs').checked,
      pocket_depth: 12.0
    };

    try {
      var res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      
      state.toolpaths = data.toolpaths || [];
      state.stock = data.stock;

      $('gcode-display').textContent = data.gcode;
      $('btn-download').style.display = 'inline-flex';
      $('gen-stats').textContent = 'Строк G-code: ' + data.line_count + ' | Подача: ' + data.feeds_speeds.feed_mm_min + ' мм/мин';

      renderCanvas();
    } catch (e) {
      alert('Ошибка генерации: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Сгенерировать High-End G-code';
    }
  }

  // 4. Отрисовка 3D Canvas в изометрии
  var canvas = $('cam-canvas');
  var ctx = canvas.getContext('2d');

  function resizeCanvas() {
    var rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    renderCanvas();
  }

  function project(x, y, z) {
    // Центрируем заготовку
    var cx = x - state.stock.width / 2;
    var cy = y - state.stock.height / 2;
    var cz = z;

    // Вращение вокруг Z
    var radZ = (state.rotZ * Math.PI) / 180;
    var x1 = cx * Math.cos(radZ) - cy * Math.sin(radZ);
    var y1 = cx * Math.sin(radZ) + cy * Math.cos(radZ);

    // Вращение вокруг X (наклон)
    var radX = (state.rotX * Math.PI) / 180;
    var y2 = y1 * Math.cos(radX) - cz * Math.sin(radX);
    var z2 = y1 * Math.sin(radX) + cz * Math.cos(radX);

    var scale = (canvas.width / 600) * state.zoom;
    return {
      px: canvas.width / 2 + x1 * scale + state.panX,
      py: canvas.height / 2 - y2 * scale + state.panY
    };
  }

  function renderCanvas() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    var sw = state.stock.width;
    var sh = state.stock.height;
    var st = state.stock.thickness;

    // 1. Отрисовка заготовки (полупрозрачный объем дерева)
    var corners = [
      project(0, 0, 0), project(sw, 0, 0),
      project(sw, sh, 0), project(0, sh, 0),
      project(0, 0, -st), project(sw, 0, -st),
      project(sw, sh, -st), project(0, sh, -st)
    ];

    // Верхняя грань
    ctx.fillStyle = 'rgba(217, 119, 6, 0.12)';
    ctx.strokeStyle = '#d97706';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(corners[0].px, corners[0].py);
    ctx.lineTo(corners[1].px, corners[1].py);
    ctx.lineTo(corners[2].px, corners[2].py);
    ctx.lineTo(corners[3].px, corners[3].py);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Боковые ребра заготовки
    ctx.strokeStyle = 'rgba(217, 119, 6, 0.4)';
    for (var i = 0; i < 4; i++) {
      ctx.beginPath();
      ctx.moveTo(corners[i].px, corners[i].py);
      ctx.lineTo(corners[i + 4].px, corners[i + 4].py);
      ctx.stroke();
    }
    // Нижняя грань
    ctx.beginPath();
    ctx.moveTo(corners[4].px, corners[4].py);
    ctx.lineTo(corners[5].px, corners[5].py);
    ctx.lineTo(corners[6].px, corners[6].py);
    ctx.lineTo(corners[7].px, corners[7].py);
    ctx.closePath();
    ctx.stroke();

    // 2. Отрисовка траекторий
    if (!state.toolpaths.length) {
      // Подсказка, если еще не сгенерировано
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Нажмите «Сгенерировать High-End G-code» для построения 3D траекторий', canvas.width / 2, canvas.height / 2 + 100);
      return;
    }

    state.toolpaths.forEach(function (tp) {
      var pts = tp.points;
      if (!pts || pts.length < 2) return;

      ctx.beginPath();
      var p0 = project(pts[0][0], pts[0][1], pts[0][2]);
      ctx.moveTo(p0.px, p0.py);

      for (var j = 1; j < pts.length; j++) {
        var pj = project(pts[j][0], pts[j][1], pts[j][2]);
        ctx.lineTo(pj.px, pj.py);
      }

      if (tp.type === 'profile_3d_tabs') {
        ctx.strokeStyle = '#f59e0b'; // Amber для 3D мостиков
        ctx.lineWidth = 2.5;
      } else {
        ctx.strokeStyle = '#38bdf8'; // Синий для выборки по волокнам
        ctx.lineWidth = 1.2;
      }
      ctx.stroke();
    });
  }

  // Мышь: вращение и сдвиг 3D вида
  canvas.addEventListener('mousedown', function (e) {
    state.isDragging = true;
    state.dragStart = { x: e.clientX, y: e.clientY };
  });

  window.addEventListener('mousemove', function (e) {
    if (!state.isDragging) return;
    var dx = e.clientX - state.dragStart.x;
    var dy = e.clientY - state.dragStart.y;
    state.dragStart = { x: e.clientX, y: e.clientY };

    if (e.shiftKey) {
      state.panX += dx * 1.5;
      state.panY += dy * 1.5;
    } else {
      state.rotZ += dx * 0.6;
      state.rotX = Math.max(10, Math.min(85, state.rotX - dy * 0.6));
    }
    renderCanvas();
  });

  window.addEventListener('mouseup', function () { state.isDragging = false; });

  canvas.addEventListener('wheel', function (e) {
    e.preventDefault();
    state.zoom *= e.deltaY > 0 ? 0.9 : 1.1;
    state.zoom = Math.max(0.4, Math.min(6.0, state.zoom));
    renderCanvas();
  });

  // Переключение вкладок 3D / G-code
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var view = btn.getAttribute('data-view');
      $('view-3d-wrap').style.display = view === '3d' ? 'block' : 'none';
      $('view-gcode-wrap').style.display = view === 'gcode' ? 'block' : 'none';
      if (view === '3d') resizeCanvas();
    });
  });

  // Слушатели событий формы
  ['tool-dia', 'tool-flutes', 'tool-rpm', 'tool-stepdown', 'stock-material'].forEach(function (id) {
    $(id).addEventListener('input', updateChipLoad);
    $(id).addEventListener('change', updateChipLoad);
  });

  $('grain-angle').addEventListener('input', updateGrainVisual);
  $('btn-generate').addEventListener('click', generateGcode);

  window.addEventListener('resize', resizeCanvas);

  // Инициализация
  updateGrainVisual();
  updateChipLoad();
  setTimeout(resizeCanvas, 50);
})();
