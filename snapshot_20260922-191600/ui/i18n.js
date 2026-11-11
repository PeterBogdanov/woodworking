/* boardcam UI — язык интерфейса. Словарь «русская строка → английская»;
   русский язык = сами ключи. Переключение перезагружает страницу. */
(function (global) {
'use strict';

var EN = {
  /* шапка, вкладки */
  'Задания': 'Jobs',
  'Библиотека': 'Library',
  'Прогоны': 'Runs',

  /* задание */
  'Новое задание': 'New job',
  'Задание': 'Job',
  'Задание ': 'Job ',
  'Имя': 'Name',
  'латиница, цифры, «_», «.», «-»': 'latin letters, digits, "_", ".", "-"',
  'Имя задания: только латиница, цифры, «_», «.», «-»': 'Job name: latin letters, digits, "_", ".", "-" only',
  'Форма': 'Shape',
  'Набор параметров': 'Preset',
  'Материал': 'Material',
  'Параметры формы': 'Shape parameters',
  'Параметр': 'Parameter',
  'Из набора': 'From preset',
  'Переопределение': 'Override',
  'Опции': 'Options',
  'Выравнивание заготовки (flatten)': 'Blank flattening (flatten)',
  'автоматически': 'automatic',
  'включено': 'on',
  'выключено': 'off',
  'Обрезка контура (profile_mode)': 'Profile cut-out (profile_mode)',
  'без переворота (full)': 'no flip (full)',
  'с переворотом (flip)': 'with flip (flip)',
  'Заметки': 'Notes',
  'Сохранить': 'Save',
  'Удалить': 'Delete',
  'План': 'Plan',
  'Сгенерировать G-code': 'Generate G-code',
  'Вид сверху': 'Top view',
  'Генерация': 'Generation',
  'Заданий пока нет': 'No jobs yet',
  'ошибка: ': 'error: ',
  ' (нет в каталоге)': ' (not in the catalogue)',
  '— без набора —': '— no preset —',
  ' (нет у формы)': ' (not in this shape)',
  '— не выбран —': '— not selected —',
  ' (эталон)': ' (reference)',
  ' (нет в библиотеке)': ' (not in the library)',
  ' (нет в библиотеке или без этой роли)': ' (not in the library, or lacks this role)',
  'Форма не найдена': 'Shape not found',
  '— из набора —': '— from preset —',
  'Сбросить переопределение': 'Clear the override',
  'У формы нет параметров': 'This shape has no parameters',
  'Не выбрана форма': 'No shape selected',
  'Сохранение…': 'Saving…',
  'Сохранено': 'Saved',
  'Удаление…': 'Deleting…',
  'сервер отказал': 'the server refused',
  'Точно удалить задание «': 'Really delete job "',
  'Точно удалить ': 'Really delete ',
  '»?': '"?',
  'Да': 'Yes',
  'Нет': 'No',
  'Считаем план…': 'Computing the plan…',
  'План…': 'Plan…',
  'Генерация G-code… ': 'Generating G-code… ',
  'Генерация…': 'Generating…',

  /* роли и фрезы */
  'Фрезы': 'Bits',
  'Фреза': 'Bit',
  'фрезу': 'bit',
  'материал': 'material',
  'черновая': 'roughing',
  'чистовая': 'finishing',
  'контур': 'profile',
  'канавка': 'groove',
  'выравнивание': 'surfacing',
  'Роль': 'Role',
  'Роли': 'Roles',
  'Почему': 'Why',
  'Операции': 'Operations',

  /* план и геометрия */
  'План готов': 'Plan ready',
  ' · материал: ': ' · material: ',
  'План не составлен': 'No plan produced',
  'Форма: ': 'Shape: ',
  'Заготовка: ': 'Blank: ',
  'Толщина: ': 'Thickness: ',
  ', ноль: ': ', origin: ',
  ' мм': ' mm',
  'Карманы': 'Pockets',
  'Площадь, см²': 'Area, cm²',
  'Глубина, мм': 'Depth, mm',
  'R дна, мм': 'Floor R, mm',
  'Частей': 'Parts',
  'Сообщения геометрии': 'Geometry messages',

  /* генерация и прогоны */
  'НА СТАНОК НЕ НЕСТИ — генерация отклонена': 'DO NOT RUN ON THE MACHINE — generation refused',
  'НА СТАНОК НЕ НЕСТИ': 'DO NOT RUN ON THE MACHINE',
  'ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ': 'GEOMETRY AND TOOLPATHS ARE OK',
  'ЕСТЬ ЗАМЕЧАНИЯ - СМ. ВЫШЕ': 'THERE ARE PROBLEMS - SEE ABOVE',
  'прогон ': 'run ',
  'Прогон': 'Run',
  'Файлы G-code': 'G-code files',
  'Обновить': 'Refresh',
  'Штамп': 'Stamp',
  'Форма/набор': 'Shape / preset',
  'Итог': 'Verdict',
  'Время': 'Time',
  'Прогонов нет': 'No runs',
  'Загрузка отчёта…': 'Loading the report…',
  'Отчёт не загружен: ': 'Report not loaded: ',
  '3-D просмотр недоступен: ': '3-D view unavailable: ',
  'Модель (STL)': 'Model (STL)',
  'Заготовка': 'Blank',
  'Ноль X0Y0': 'Origin X0Y0',
  'Обработанная поверхность': 'Machined surface',
  'Загрузка модели…': 'Loading the model…',
  'ЛКМ — вращение, колесо — масштаб, ПКМ или Shift+ЛКМ — сдвиг, двойной клик — вписать':
    'LMB — rotate, wheel — zoom, RMB or Shift+LMB — pan, double click — fit',

  /* библиотека */
  'Добавить фрезу': 'Add a bit',
  'Добавить материал': 'Add a material',
  'Название': 'Title',
  'Тип': 'Type',
  'Обороты': 'RPM',
  'Подача': 'Feed',
  'Материалы': 'Materials',
  'Янка': 'Janka',
  'Диск': 'Dial',
  'Эталон': 'Reference',
  'Станок': 'Machine',
  'Фрез нет': 'No bits',
  'Материалов нет': 'No materials',
  'Новая запись': 'New entry',
  'Закрыть': 'Close',
  'Нужен id': 'An id is required',
  'Короткое имя': 'Short name',
  'Ø, мм (dia)': 'Ø, mm (dia)',
  'R угла, мм (corner_r)': 'Corner R, mm (corner_r)',
  'Длина режущей части, мм (loc)': 'Length of cut, mm (loc)',
  'Хвостовик, мм (shank)': 'Shank, mm (shank)',
  'Обороты (rpm)': 'RPM (rpm)',
  'Обороты макс. (rpm_max)': 'RPM max (rpm_max)',
  'Подача, мм/мин (feed)': 'Feed, mm/min (feed)',
  'Врезание, мм/мин (plunge)': 'Plunge, mm/min (plunge)',
  'Рампа, мм/мин (ramp)': 'Ramp, mm/min (ramp)',
  'Подача по контуру, мм/мин (feed_contour, необяз.)': 'Contour feed, mm/min (feed_contour, optional)',
  'Шаг между проходами (stepover)': 'Stepover (stepover)',
  'Глубина за проход (doc)': 'Depth of cut (doc)',
  'Номер инструмента (num)': 'Tool number (num)',
  'Цвет (#rrggbb)': 'Colour (#rrggbb)',
  'Подсказка в интерфейсе': 'Hint shown in the interface',
  'Твёрдость Янка (janka, пусто = нет)': 'Janka hardness (janka, empty = none)',
  'Коэффициент подачи (feed_scale)': 'Feed factor (feed_scale)',
  'Положение диска Makita (dial)': 'Makita speed dial (dial)',
  'Эталонный материал': 'Reference material',
  'JSON не разбирается: ': 'JSON does not parse: ',
  'Ожидается JSON-объект': 'A JSON object is expected',
  'Янка ': 'Janka ',
  'подача ×': 'feed ×',
  ' об/мин': ' rpm',
  'диск ': 'dial ',

  /* загрузка данных и ошибки */
  'OpenSCAD не найден': 'OpenSCAD not found',
  'Библиотека: ': 'Library: ',
  'Не удалось опросить сервер (/api/doctor): ': 'Could not query the server (/api/doctor): ',
  'Формы не загружены: ': 'Shapes not loaded: ',
  'Библиотека не загружена: ': 'Library not loaded: ',
  'Список заданий не загружен: ': 'Job list not loaded: ',
  'Список прогонов не загружен: ': 'Run list not loaded: ',
  'Превью не получено (': 'Preview not received (',
  'ответ не JSON': 'response is not JSON',
  'Ошибка запуска: ': 'Startup error: ',
  ' КБ': ' KB',
  ' мин': ' min',
  ' с': ' s',
  '0 с': '0 s',
  ' «': ' "'
};

var LANG = 'ru';
try { if (localStorage.getItem('boardcam.lang') === 'en') LANG = 'en'; } catch (e) { /* приватный режим */ }

function has(s) { return Object.prototype.hasOwnProperty.call(EN, s); }
function t(s) { return (LANG === 'en' && has(s)) ? EN[s] : s; }

/* Статическая разметка index.html: переводим текстовые узлы и подписи атрибутов. */
function translateDom(root) {
  var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false), n;
  var texts = [];
  while ((n = w.nextNode())) texts.push(n);
  texts.forEach(function (node) {
    var tag = node.parentNode && node.parentNode.nodeName;
    if (tag === 'SCRIPT' || tag === 'STYLE') return;
    var s = node.nodeValue, body = s.trim();
    if (!body || !has(body)) return;
    node.nodeValue = s.replace(body, EN[body]);
  });
  Array.prototype.forEach.call(root.querySelectorAll('[placeholder],[title],[alt]'), function (el) {
    ['placeholder', 'title', 'alt'].forEach(function (a) {
      var v = el.getAttribute(a);
      if (v && has(v)) el.setAttribute(a, EN[v]);
    });
  });
}

document.addEventListener('DOMContentLoaded', function () {
  document.documentElement.lang = LANG;
  if (LANG === 'en') translateDom(document.body);
  var sel = document.getElementById('lang');
  if (!sel) return;
  sel.value = LANG;
  sel.addEventListener('change', function () {
    try { localStorage.setItem('boardcam.lang', sel.value); } catch (e) { /* приватный режим */ }
    location.reload();
  });
});

global.t = t;
global.BoardcamLang = LANG;
})(window);
