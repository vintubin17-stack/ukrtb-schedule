/* ------------------------------------------------------------------
   Расписание УКРТБ — клиентская логика.
   Загружает данные из локального API (/api/schedule) и рисует карточки
   дней. Все данные приходят уже нормализованными с бэкенда.
   ------------------------------------------------------------------ */

(function () {
    'use strict';

    var body = document.body;

    // Два режима работы одного и того же интерфейса:
    //   api    — данные берутся с локального Flask-сервера (/api/schedule);
    //   static — страница лежит на GitHub Pages, данные читаются из
    //            заранее собранного data.json (его готовит build_static.py
    //            на компьютере, откуда портал колледжа доступен).
    var IS_STATIC = body.dataset.mode === 'static';

    var cfg = {
        group: body.dataset.defaultGroup || 'КСК-40',
        days: parseInt(body.dataset.defaultDays || '3', 10) || 3,
        sourceUrl: body.dataset.sourceUrl || 'https://study.ukrtb.ru/schedule',
        autoRefreshMs: 15 * 60 * 1000, // мягкое автообновление раз в 15 минут
    };

    var el = {
        days: document.getElementById('days'),
        groupInput: document.getElementById('group-input'),
        groupTitle: document.getElementById('group-title'),
        groupList: document.getElementById('group-list'),
        rangeLabel: document.getElementById('range-label'),
        refreshBtn: document.getElementById('refresh-btn'),
        refreshIcon: document.getElementById('refresh-icon'),
        refreshLabel: document.getElementById('refresh-label'),
        sourceBadge: document.getElementById('source-badge'),
        updatedBadge: document.getElementById('updated-badge'),
        totalBadge: document.getElementById('total-badge'),
        notice: document.getElementById('notice'),
        errorBox: document.getElementById('error-box'),
        errorTitle: document.getElementById('error-title'),
        errorText: document.getElementById('error-text'),
        errorSuggestions: document.getElementById('error-suggestions'),
        errorRetry: document.getElementById('error-retry'),
        dateInput: document.getElementById('date-input'),
        prevDay: document.getElementById('prev-day'),
        nextDay: document.getElementById('next-day'),
        quickChips: document.getElementById('quick-chips'),
        daysSwitch: document.getElementById('days-switch'),
        rangeHint: document.getElementById('range-hint'),
        themeBtn: document.getElementById('theme-btn'),
        themeIcon: document.getElementById('theme-icon'),
    };

    var state = {
        group: cfg.group,
        days: cfg.days,
        start: todayIso(),        // дата начала окна, ГГГГ-ММ-ДД
        loading: false,
        loadedOnce: false,
        groupsLoaded: false,
        publishedRange: null,
        themeMode: 'auto',        // auto | light | dark
        themeTurns: 0,            // сколько раз повернулась иконка темы
    };

    var SOURCE_META = {
        live: {
            text: 'Актуальные данные портала',
            cls: 'bg-emerald-100 text-emerald-800 ring-emerald-200',
            dot: 'bg-emerald-500',
        },
        cache: {
            text: 'Из локального кэша',
            cls: 'bg-amber-100 text-amber-900 ring-amber-200',
            dot: 'bg-amber-500',
        },
        sample: {
            text: 'Демонстрационные данные',
            cls: 'bg-violet-100 text-violet-800 ring-violet-200',
            dot: 'bg-violet-500',
        },
        mixed: {
            text: 'Часть данных из кэша',
            cls: 'bg-sky-100 text-sky-800 ring-sky-200',
            dot: 'bg-sky-500',
        },
        error: {
            text: 'Данные недоступны',
            cls: 'bg-rose-100 text-rose-800 ring-rose-200',
            dot: 'bg-rose-500',
        },
        pending: {
            // День за пределами собранного снимка — это не сбой,
            // поэтому и вид нейтральный, а не предупреждающий.
            text: 'Ещё не собрано',
            cls: 'bg-slate-100 text-slate-700 ring-slate-200',
            dot: 'bg-slate-400',
            textCls: 'text-slate-500',
        },
    };

    // --- Утилиты ------------------------------------------------------

    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function plural(count, forms) {
        var n = Math.abs(count) % 100;
        var n1 = n % 10;
        if (n > 10 && n < 20) return forms[2];
        if (n1 > 1 && n1 < 5) return forms[1];
        if (n1 === 1) return forms[0];
        return forms[2];
    }

    function pairsLabel(count) {
        return count + ' ' + plural(count, ['пара', 'пары', 'пар']);
    }

    // --- Работа с датами ----------------------------------------------

    // Локальная дата в формате ГГГГ-ММ-ДД.
    // Именно локальная: toISOString() переводит в UTC и может сдвинуть день.
    function toIsoDate(value) {
        var d = (value instanceof Date) ? value : new Date(value + 'T00:00:00');
        if (isNaN(d.getTime())) return null;
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    function todayIso() {
        return toIsoDate(new Date());
    }

    function isoShift(iso, days) {
        var d = new Date(iso + 'T00:00:00');
        if (isNaN(d.getTime())) return todayIso();
        d.setDate(d.getDate() + days);
        return toIsoDate(d);
    }

    function humanDate(iso) {
        var d = new Date(iso + 'T00:00:00');
        if (isNaN(d.getTime())) return iso;
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear();
    }

    // --- Классы кнопок выбора даты ------------------------------------

    var CHIP_BASE = 'quick-chip rounded-full border px-3 py-1.5 text-xs font-semibold transition ';
    var CHIP_ON = CHIP_BASE + 'border-sky-600 bg-sky-600 text-white';
    var CHIP_OFF = CHIP_BASE + 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100';

    var DAYS_BASE = 'days-btn rounded-lg px-3 py-1.5 text-xs font-semibold transition ';
    var DAYS_ON = DAYS_BASE + 'bg-card text-sky-700 shadow-sm';
    var DAYS_OFF = DAYS_BASE + 'text-slate-600 hover:text-slate-900';

    var GRID_BY_DAYS = {
        1: 'mt-6 grid gap-5 lg:max-w-2xl',
        2: 'mt-6 grid gap-5 lg:grid-cols-2',
    };

    function gridClass(days) {
        return GRID_BY_DAYS[days] || 'mt-6 grid gap-5 lg:grid-cols-3';
    }

    function setBadge(node, text, extraCls, dotCls) {
        if (!text) {
            node.hidden = true;
            return;
        }
        node.className =
            'badge inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ' +
            (extraCls || 'bg-slate-100 text-slate-700 ring-slate-200');
        node.innerHTML =
            (dotCls ? '<span class="h-1.5 w-1.5 rounded-full ' + dotCls + '"></span>' : '') +
            '<span>' + escapeHtml(text) + '</span>';
        node.hidden = false;
    }

    // --- Тема: авто, светлая, тёмная -----------------------------------
    //
    // Палитра интерфейса собрана на CSS-переменных (theme.css), поэтому
    // переключение темы — это один класс на <html>, а не перерисовка.
    //
    // Режим «авто» не спрашивает систему, а смотрит на часы: вечером
    // и рано утром расписание удобнее читать в тёмной теме. Это
    // предсказуемее системной настройки: поведение одинаково на всех
    // устройствах и объясняется одной фразой.

    var THEME_KEY = 'ukrtb-theme';
    var THEME_MODES = ['auto', 'light', 'dark'];
    var THEME_TITLES = {
        auto: 'Тема: авто — тёмная с 20:00 до 7:00',
        light: 'Тема: светлая',
        dark: 'Тема: тёмная',
    };

    var THEME_ICONS = {
        light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
               'stroke-linecap="round" class="h-5 w-5"><circle cx="12" cy="12" r="4"/>' +
               '<path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2' +
               'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
        dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
              'stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5">' +
              '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>',
        auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
              'class="h-5 w-5"><circle cx="12" cy="12" r="9"/>' +
              '<path d="M12 3a9 9 0 0 0 0 18Z" fill="currentColor" stroke="none"/></svg>',
    };

    function readThemeMode() {
        try {
            var saved = window.localStorage.getItem(THEME_KEY);
            return THEME_MODES.indexOf(saved) >= 0 ? saved : 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    function autoThemeIsDark() {
        var hour = new Date().getHours();
        return hour >= 20 || hour < 7;
    }

    function effectiveTheme(mode) {
        if (mode === 'light') return 'light';
        if (mode === 'dark') return 'dark';
        return autoThemeIsDark() ? 'dark' : 'light';
    }

    function applyTheme(mode, options) {
        options = options || {};
        var effective = effectiveTheme(mode);
        state.themeMode = mode;

        document.documentElement.classList.toggle('dark', effective === 'dark');
        try { window.localStorage.setItem(THEME_KEY, mode); } catch (e) { /* приватный режим */ }

        if (el.themeIcon) {
            el.themeIcon.innerHTML = THEME_ICONS[mode] || THEME_ICONS.auto;
            if (!options.skipRotation) {
                // Пол-оборота за каждое нажатие — заметно, но не мешает.
                state.themeTurns += 1;
                el.themeIcon.style.transform = 'rotate(' + (state.themeTurns * 180) + 'deg)';
            }
        }
        if (el.themeBtn) {
            el.themeBtn.title = THEME_TITLES[mode] + ' — нажмите, чтобы сменить';
        }

        // Цвет адресной строки браузера под тему.
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            meta.setAttribute('content', effective === 'dark' ? '#0f172a' : '#0284c7');
        }

        // Если страница открыта внутри iOS-приложения, скажем ему тему:
        // тогда строка состояния подстроит цвет текста.
        try {
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.theme) {
                window.webkit.messageHandlers.theme.postMessage(effective);
            }
        } catch (e) { /* открыто в браузере — это нормально */ }

        if (!options.silent) {
            showThemeHint(mode, effective);
        }
    }

    function cycleTheme() {
        var index = THEME_MODES.indexOf(state.themeMode);
        applyTheme(THEME_MODES[(index + 1) % THEME_MODES.length]);
    }

    /// Короткая всплывающая подсказка о выбранной теме.
    function showThemeHint(mode, effective) {
        var text = mode === 'auto'
            ? 'Авто · сейчас ' + (effective === 'dark' ? 'тёмная' : 'светлая')
            : (effective === 'dark' ? 'Тёмная тема' : 'Светлая тема');

        var hint = document.getElementById('theme-hint');
        if (!hint) {
            hint = document.createElement('div');
            hint.id = 'theme-hint';
            hint.className = 'pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4';
            hint.innerHTML = '<span class="rounded-full bg-sky-600 px-4 py-2 text-xs font-semibold ' +
                             'text-white shadow-lg transition-opacity duration-300"></span>';
            document.body.appendChild(hint);
        }

        var label = hint.firstChild;
        label.textContent = text;
        label.style.opacity = '1';

        window.clearTimeout(hint.dataset.timer);
        hint.dataset.timer = window.setTimeout(function () {
            label.style.opacity = '0';
        }, 1600);
    }

    // --- Рендер -------------------------------------------------------

    function renderSkeleton() {
        el.days.className = gridClass(state.days);
        var card = '';
        for (var i = 0; i < Math.min(state.days, 3); i++) {
            card +=
                '<article class="day-card overflow-hidden rounded-2xl border border-slate-200 bg-card shadow-sm">' +
                    '<div class="border-b border-slate-100 px-5 py-4">' +
                        '<div class="skeleton h-3 w-24"></div>' +
                        '<div class="skeleton mt-2.5 h-5 w-32"></div>' +
                    '</div>' +
                    '<div class="space-y-3 px-5 py-4">' +
                        '<div class="skeleton h-4 w-3/4"></div>' +
                        '<div class="skeleton h-3 w-1/2"></div>' +
                        '<div class="skeleton h-3 w-2/3"></div>' +
                    '</div>' +
                '</article>';
        }
        el.days.innerHTML = card;
        el.days.setAttribute('aria-busy', 'true');
    }

    function renderLesson(lesson) {
        var chips = '';
        if (lesson.type) {
            chips += '<span class="chip rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">' +
                escapeHtml(lesson.type) + '</span>';
        }
        if (lesson.remote) {
            chips += '<span class="chip chip-remote rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 ring-1 ring-blue-100">' +
                'Дистанционно</span>';
        }
        if (lesson.subgroup) {
            chips += '<span class="chip rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700 ring-1 ring-indigo-100">' +
                escapeHtml(lesson.subgroup) + ' подгруппа</span>';
        }

        // Строка аудитории: для дистанционных пар без кабинета не показываем
        // ничего — формат занятия уже отмечен бейджем «Дистанционно».
        var room = lesson.room_label
            ? '<p class="lesson-meta mt-1.5 flex flex-wrap items-center gap-x-1.5 text-[13px] text-slate-600">' +
                  '<span class="font-medium text-slate-700">ауд. ' + escapeHtml(lesson.room_label) + '</span>' +
                  (lesson.room && lesson.room_title
                      ? '<span class="text-slate-400">·</span><span class="text-slate-500">' + escapeHtml(lesson.room_title) + '</span>'
                      : '') +
              '</p>'
            : '';

        // Ссылку на подключение портал даёт только для дистанционных пар.
        var link = (lesson.remote && lesson.teacher_link)
            ? '<a class="lesson-link mt-2 inline-flex items-center gap-1 text-xs font-semibold text-sky-700 hover:text-sky-900" ' +
                  'href="' + escapeHtml(lesson.teacher_link) + '" target="_blank" rel="noopener noreferrer">' +
                  '<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                  '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5v13h13v-8.5"/><path stroke-linecap="round" d="M10 14 20 4m0 0h-4m4 0v4"/></svg>' +
                  'Подключиться</a>'
            : '';

        return (
            '<li class="lesson flex gap-4 px-5 py-4 transition hover:bg-slate-50/70">' +
                '<div class="lesson-left flex w-16 shrink-0 flex-col items-center">' +
                    '<span class="pair-number flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sm font-bold text-sky-800">' +
                        escapeHtml(lesson.number || '–') +
                    '</span>' +
                    '<span class="lesson-time mt-1.5 text-[11px] leading-tight text-slate-500">' +
                        escapeHtml(lesson.start || '') +
                    '</span>' +
                    '<span class="text-[11px] leading-tight text-slate-400">' + escapeHtml(lesson.end || '') + '</span>' +
                '</div>' +
                '<div class="min-w-0 flex-1">' +
                    '<p class="lesson-title text-[15px] font-semibold leading-snug text-slate-900">' +
                        escapeHtml(lesson.discipline || 'Без названия') + '</p>' +
                    (chips ? '<div class="mt-1.5 flex flex-wrap gap-1.5">' + chips + '</div>' : '') +
                    (lesson.teacher
                        ? '<p class="lesson-meta mt-1.5 text-[13px] text-slate-600">' + escapeHtml(lesson.teacher) + '</p>'
                        : '') +
                    room +
                    link +
                '</div>' +
            '</li>'
        );
    }

    function renderDay(day) {
        var badge = '';
        if (day.is_today) {
            badge = '<span class="badge badge-today rounded-full bg-sky-600 px-2.5 py-1 text-[11px] font-semibold text-white">Сегодня</span>';
        } else if (day.is_tomorrow) {
            badge = '<span class="badge rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200">Завтра</span>';
        } else if (day.is_past) {
            badge = '<span class="badge rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-400 ring-1 ring-slate-200">Прошло</span>';
        }

        var daySource = '';
        if (day.source && day.source !== 'live') {
            var meta = SOURCE_META[day.source];
            if (meta) {
                daySource = '<span class="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium ' +
                    (meta.textCls || 'text-amber-700') + '">' +
                    '<span class="h-1.5 w-1.5 rounded-full ' + meta.dot + '"></span>' + escapeHtml(meta.text) + '</span>';
            }
        }

        var content;
        if (day.has_lessons) {
            content = '<ul class="divide-y divide-slate-100">' + day.lessons.map(renderLesson).join('') + '</ul>';
        } else if (day.source === 'pending' || day.notCollected) {
            content =
                '<div class="empty-day px-5 py-12 text-center">' +
                    '<svg class="mx-auto h-9 w-9 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
                    '<circle cx="12" cy="12" r="9"/><path stroke-linecap="round" d="M12 7v5l3 2"/>' +
                    '</svg>' +
                    '<p class="mt-3 text-sm font-medium text-slate-600">Данных пока нет</p>' +
                    '<p class="mt-1 text-xs text-slate-400">День появится в следующем обновлении</p>' +
                '</div>';
        } else if (day.source === 'error' || day.unavailable) {
            content =
                '<div class="empty-day px-5 py-12 text-center">' +
                    '<svg class="mx-auto h-9 w-9 text-rose-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
                    '<circle cx="12" cy="12" r="9"/><path stroke-linecap="round" d="M12 8v5m0 3h.01"/>' +
                    '</svg>' +
                    '<p class="mt-3 text-sm font-medium text-rose-700">Данные недоступны</p>' +
                    '<p class="mt-1 text-xs text-slate-500">Портал не отвечает, сохранённых данных нет</p>' +
                '</div>';
        } else {
            content =
                '<div class="empty-day px-5 py-12 text-center">' +
                    '<svg class="mx-auto h-9 w-9 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
                    '<rect x="3" y="5" width="18" height="16" rx="2"/><path stroke-linecap="round" d="M3 10h18M8 3v4m8-4v4"/>' +
                    '</svg>' +
                    '<p class="mt-3 text-sm font-medium text-slate-600">Занятий нет</p>' +
                    '<p class="mt-1 text-xs text-slate-400">' +
                        (day.is_weekend ? 'Выходной день' : 'Расписание на этот день не опубликовано') +
                    '</p>' +
                '</div>';
        }

        return (
            '<article class="day-card flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-card shadow-sm ' +
                (day.is_today ? 'ring-2 ring-sky-500/60' : '') + '">' +
                '<header class="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">' +
                    '<div class="min-w-0">' +
                        '<p class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">' +
                            escapeHtml(day.weekday_short) + ' · ' + escapeHtml(day.date_label) +
                        '</p>' +
                        '<h2 class="mt-0.5 truncate text-lg font-semibold text-slate-900">' + escapeHtml(day.weekday) + '</h2>' +
                        '<p class="mt-0.5 text-xs text-slate-500">' +
                            (day.has_lessons ? pairsLabel(day.lessons_count) : 'нет занятий') +
                        '</p>' +
                        daySource +
                    '</div>' +
                    '<div class="shrink-0">' + badge + '</div>' +
                '</header>' +
                '<div class="flex-1">' + content + '</div>' +
            '</article>'
        );
    }

    function render(data) {
        var days = data.days || [];
        el.days.className = gridClass(days.length);
        el.days.innerHTML = days.map(renderDay).join('');
        el.days.setAttribute('aria-busy', 'false');

        el.groupTitle.textContent = data.group;
        el.groupInput.value = data.group;

        // Синхронизируем панель выбора даты с тем, что реально показано.
        if (data.start_date) {
            state.start = data.start_date;
            el.dateInput.value = data.start_date;
        }
        state.publishedRange = data.published_range || null;
        applyPublishedRange(state.publishedRange);

        if (days.length) {
            var first = days[0];
            var last = days[days.length - 1];
            el.rangeLabel.textContent = days.length > 1
                ? first.date_label + ' — ' + last.date_label + ' (' + days.length + ' ' +
                  plural(days.length, ['день', 'дня', 'дней']) + ')'
                : first.date_label;
        }

        var total = days.reduce(function (sum, day) { return sum + (day.lessons_count || 0); }, 0);
        setBadge(el.totalBadge, pairsLabel(total) + ' за период', 'bg-slate-100 text-slate-700 ring-slate-200');

        var meta = SOURCE_META[data.source] || SOURCE_META.live;
        setBadge(el.sourceBadge, meta.text, meta.cls, meta.dot);

        if (data.generated_at) {
            var when = new Date(data.generated_at);
            if (!isNaN(when.getTime())) {
                var time = when.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
                setBadge(el.updatedBadge, 'Обновлено в ' + time, 'bg-slate-100 text-slate-700 ring-slate-200');
            }
        }

        if (data.warnings && data.warnings.length) {
            el.notice.textContent = data.warnings.join(' ');
            el.notice.hidden = false;
        } else {
            // Чистим и текст: иначе старое предупреждение остаётся в DOM
            el.notice.textContent = '';
            el.notice.hidden = true;
        }

        syncControls();
        syncUrl();
    }

    // Подсказка о том, за какой период портал вообще публикует расписание,
    // и ограничение выбора даты этим периодом.
    function applyPublishedRange(range) {
        var min = range && range.min ? range.min : '';
        var max = range && range.max ? range.max : '';
        el.dateInput.min = min;
        el.dateInput.max = max;

        if (min && max) {
            el.rangeHint.textContent =
                'Портал публикует расписание за период ' + humanDate(min) + ' — ' + humanDate(max) +
                '. Даты вне этого периода будут пустыми.';
            el.rangeHint.hidden = false;
        } else {
            el.rangeHint.hidden = true;
        }
    }

    // Подсветка активных кнопок: быстрые переходы и выбор числа дней.
    // Активной считается только та кнопка, чья дата совпадает с началом
    // показанного окна — иначе подсветка читалась бы как несколько фильтров.
    function syncControls() {
        var today = todayIso();

        Array.prototype.forEach.call(el.quickChips.querySelectorAll('[data-offset]'), function (btn) {
            var offset = parseInt(btn.dataset.offset, 10);
            var target = offset === 0 ? today : isoShift(today, offset);
            btn.className = (state.start === target) ? CHIP_ON : CHIP_OFF;
        });

        Array.prototype.forEach.call(el.daysSwitch.querySelectorAll('[data-days]'), function (btn) {
            btn.className = parseInt(btn.dataset.days, 10) === state.days ? DAYS_ON : DAYS_OFF;
        });
    }

    // Состояние в адресной строке — ссылку можно сохранить или переслать.
    function syncUrl() {
        // В ярлыке на домашнем экране адрес не трогаем: там это лишний
        // повод для сбоя, а поделиться ссылкой из ярлыка всё равно нельзя.
        if (window.navigator.standalone) return;
        if (!window.history || !window.history.replaceState) return;
        var params = new URLSearchParams();
        params.set('group', state.group);
        params.set('date', state.start);
        if (state.days !== cfg.days) params.set('days', String(state.days));
        try {
            window.history.replaceState(null, '', window.location.pathname + '?' + params.toString());
        } catch (e) { /* не критично */ }
    }

    // Service worker: благодаря ему ярлык на домашнем экране открывается
    // даже без сети, а не показывает «Network lost».
    function registerServiceWorker() {
        if (!IS_STATIC || !('serviceWorker' in navigator)) return;
        // Нужен защищённый контекст: https либо localhost/127.0.0.1.
        if (!window.isSecureContext) return;

        var start = function () {
            navigator.serviceWorker.register('sw.js').then(function () {
                console.info('[schedule] service worker активен: работа без сети доступна');
            }).catch(function (err) {
                console.warn('[schedule] service worker не зарегистрирован:', err);
            });
        };

        if (document.readyState === 'complete') start();
        else window.addEventListener('load', start);
    }

    function renderMessage(icon, title, text) {
        el.days.innerHTML =
            '<div class="col-span-full rounded-2xl border border-dashed border-slate-300 bg-card px-6 py-14 text-center">' +
                '<p class="text-3xl">' + icon + '</p>' +
                '<p class="mt-3 text-sm font-semibold text-slate-700">' + escapeHtml(title) + '</p>' +
                '<p class="mt-1 text-xs text-slate-500">' + escapeHtml(text) + '</p>' +
            '</div>';
        el.days.setAttribute('aria-busy', 'false');
    }

    // --- Состояния ----------------------------------------------------

    function setLoading(isLoading) {
        state.loading = isLoading;
        el.refreshBtn.disabled = isLoading;
        el.refreshIcon.classList.toggle('spin', isLoading);
        el.refreshLabel.textContent = isLoading
            ? 'Загружаем…'
            : (IS_STATIC ? 'Обновить данные' : 'Обновить расписание');
    }

    function hideError() {
        el.errorBox.hidden = true;
        el.errorSuggestions.hidden = true;
        el.errorSuggestions.innerHTML = '';
    }

    function showError(err) {
        var payload = err && err.payload;
        var title = 'Не удалось загрузить расписание';
        var text = (payload && payload.error) || err.message || 'Неизвестная ошибка.';

        if (err && err.name === 'TypeError') {
            title = 'Локальный сервер не отвечает';
            text = 'Похоже, приложение app.py остановлено. Запустите его заново и нажмите «Повторить запрос».';
        } else if (payload && payload.code === 'group_not_found') {
            title = 'Группа не найдена';
        } else if (payload && payload.code === 'source_unavailable') {
            title = 'Сайт колледжа недоступен';
        }

        el.errorTitle.textContent = title;
        el.errorText.textContent = text;

        var suggestions = (payload && payload.suggestions) || [];
        if (suggestions.length) {
            el.errorSuggestions.innerHTML = suggestions.map(function (name) {
                return '<button type="button" data-group="' + escapeHtml(name) + '" ' +
                    'class="rounded-full border border-rose-300 bg-card px-2.5 py-1 text-xs font-semibold text-rose-700 transition hover:bg-rose-100">' +
                    escapeHtml(name) + '</button>';
            }).join('');
            el.errorSuggestions.hidden = false;
        }

        el.errorBox.hidden = false;
        renderMessage('📭', 'Данных пока нет', 'Исправьте проблему и повторите запрос.');
    }

    // --- Источник данных: Flask API или статический data.json ----------

    var staticCache = { payload: null };

    function loadStaticData(force) {
        if (staticCache.payload && !force) {
            return Promise.resolve(staticCache.payload);
        }
        var url = 'data.json' + (force ? '?t=' + Date.now() : '');
        return fetch(url, { cache: force ? 'no-store' : 'default' })
            .then(function (r) {
                if (!r.ok) throw new Error('Не удалось загрузить data.json (' + r.status + ')');
                return r.json();
            })
            .then(function (data) {
                staticCache.payload = data;
                return data;
            });
    }

    // Заглушка для даты, которой нет в собранном файле.
    // Это не ошибка: день просто ещё не попал в снимок.
    var LOCAL_WEEKDAYS = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда',
                          'Четверг', 'Пятница', 'Суббота'];
    var LOCAL_WEEKDAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

    function unknownDay(iso) {
        var parsed = new Date(iso + 'T00:00:00');
        var index = isNaN(parsed.getTime()) ? -1 : parsed.getDay();

        return {
            date: iso,
            date_label: humanDate(iso),
            // День недели считаем сами: сервер для этой даты данных не дал.
            weekday: index >= 0 ? LOCAL_WEEKDAYS[index] : '',
            weekday_short: index >= 0 ? LOCAL_WEEKDAYS_SHORT[index] : '',
            is_today: iso === todayIso(),
            is_tomorrow: iso === isoShift(todayIso(), 1),
            is_past: iso < todayIso(),
            is_weekend: index === 0 || index === 6,
            has_lessons: false,
            lessons_count: 0,
            source: 'pending',
            notCollected: true,
            note: '',
            lessons: [],
        };
    }

    // Статический аналог /api/schedule: режем собранный файл по датам.
    function staticSchedule(params) {
        var wanted = params.get('date') || todayIso();
        var count = parseInt(params.get('days'), 10) || 3;
        var force = params.get('refresh') === '1';

        return loadStaticData(force).then(function (all) {
            var days = [];
            for (var i = 0; i < count; i++) {
                var iso = isoShift(wanted, i);
                days.push((all.days && all.days[iso]) || unknownDay(iso));
            }

            var warnings = (all.warnings || []).slice();

            // Перечисляем конкретные даты: «часть дат» непонятно, а «14.10.2026» —
            // сразу видно, что дело не в выбранном дне.
            var pending = days.filter(function (d) { return d.source === 'pending'; });
            if (pending.length) {
                warnings.push(
                    'За пределами собранного диапазона (' + (all.range_label || '') + '): ' +
                    pending.map(function (d) { return d.date_label; }).join(', ') +
                    '. Эти дни появятся после следующего обновления данных.'
                );
            }

            var sources = days.map(function (d) { return d.source; });
            var overall = all.source;
            if (sources.indexOf('error') >= 0) {
                overall = sources.some(function (s) { return s !== 'error'; }) ? 'mixed' : 'error';
            } else if (sources.indexOf('pending') >= 0) {
                overall = 'pending';
            }

            return {
                ok: true,
                group: all.group,
                source: overall,
                generated_at: all.generated_at,
                days_count: count,
                start_date: days.length ? days[0].date : wanted,
                end_date: days.length ? days[days.length - 1].date : wanted,
                has_lessons: days.some(function (d) { return d.has_lessons; }),
                published_range: all.published_range,
                warnings: warnings,
                days: days,
            };
        });
    }

    function requestPayload(options, params) {
        if (IS_STATIC) return staticSchedule(params);
        return fetch('/api/schedule?' + params.toString(), {
            headers: { Accept: 'application/json' },
            cache: 'no-store',
        }).then(function (response) {
            return response.json()
                .catch(function () { return null; })
                .then(function (payload) {
                    if (!response.ok) {
                        var error = new Error('HTTP ' + response.status);
                        error.payload = payload;
                        error.status = response.status;
                        throw error;
                    }
                    return payload;
                });
        });
    }

    // --- Загрузка данных ----------------------------------------------

    function fetchSchedule(options) {
        options = options || {};
        if (state.loading) return Promise.resolve();

        hideError();
        setLoading(true);
        if (!state.loadedOnce && !options.silent) {
            renderSkeleton();
        }

        var params = new URLSearchParams({
            group: state.group || cfg.group,
            date: state.start || todayIso(),
            days: String(state.days || cfg.days),
        });
        if (options.refresh) params.set('refresh', '1');
        if (options.silent) params.set('t', String(Date.now()));

        return requestPayload(options, params)
            .then(function (payload) {
                if (!payload || !payload.days) {
                    throw new Error('Сервер вернул неожиданный ответ.');
                }
                state.loadedOnce = true;
                state.group = payload.group || state.group;
                render(payload);
            })
            .catch(function (err) {
                console.error('[schedule]', err);
                showError(err);
            })
            .finally(function () {
                setLoading(false);
            });
    }

    function loadGroupOptions() {
        if (state.groupsLoaded) return;
        state.groupsLoaded = true;
        fetch('/api/groups', { headers: { Accept: 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (payload) {
                if (!payload || !payload.groups) return;
                el.groupList.innerHTML = payload.groups.slice(0, 400).map(function (name) {
                    return '<option value="' + escapeHtml(name) + '"></option>';
                }).join('');
            })
            .catch(function () { /* подсказки необязательны */ });
    }

    function applyGroup() {
        var value = (el.groupInput.value || '').trim();
        if (!value || value === state.group) {
            el.groupInput.value = state.group;
            return;
        }
        state.group = value;
        state.loadedOnce = false;
        fetchSchedule({ refresh: true });
    }

    // --- Инициализация ------------------------------------------------

    function goToDate(iso, options) {
        if (!iso) return;
        state.start = iso;
        el.dateInput.value = iso;
        state.loadedOnce = false;   // показываем скелетон: данные другой даты
        fetchSchedule(options || {});
    }

    // --- Инициализация ------------------------------------------------

    function readUrlState() {
        var params = new URLSearchParams(window.location.search);
        var group = (params.get('group') || '').trim();
        var dateParam = (params.get('date') || '').trim();
        var daysParam = parseInt(params.get('days') || '', 10);

        if (group) state.group = group;
        if (/^\d{4}-\d{2}-\d{2}$/.test(dateParam)) state.start = dateParam;
        if (!isNaN(daysParam) && daysParam >= 1 && daysParam <= 14) state.days = daysParam;

        el.groupInput.value = state.group;
        el.dateInput.value = state.start;
    }

    function checkTailwind() {
        if (!window.tailwind) {
            body.classList.add('no-tailwind');
            el.notice.hidden = false;
            el.notice.textContent =
                'Не удалось загрузить Tailwind CSS с CDN — включено упрощённое оформление. ' +
                'На данные это не влияет.';
        }
    }

    // Статическая версия: одна группа, данные из предсобранного файла.
    function setupStaticMode() {
        if (el.groupInput) {
            var wrapper = el.groupInput.parentNode;
            if (wrapper && wrapper.classList && wrapper.classList.contains('relative')) {
                wrapper.hidden = true;
            } else {
                el.groupInput.hidden = true;
            }
        }
        if (el.refreshLabel) {
            el.refreshLabel.textContent = 'Обновить данные';
        }
        var footer = document.querySelector('footer');
        if (footer) {
            // Первый абзац в шаблоне написан для режима api — переписываем.
            var first = footer.querySelector('p');
            var link = cfg.sourceUrl
                ? '<a href="' + escapeHtml(cfg.sourceUrl) + '" target="_blank" rel="noopener noreferrer" ' +
                  'class="font-medium text-sky-700 underline decoration-sky-300 underline-offset-2">study.ukrtb.ru</a>'
                : 'study.ukrtb.ru';
            if (first) {
                first.innerHTML =
                    'Источник данных: ' + link + ' (публичный API портала). ' +
                    'Страница статическая: расписание собирается на компьютере автора, ' +
                    'кнопка «Обновить данные» перечитывает файл.';
            }
            var note = document.createElement('p');
            note.className = 'mt-1.5';
            note.textContent =
                'Данные обновляются раз в несколько часов и только когда компьютер включён — ' +
                'ориентируйтесь на отметку «Обновлено» выше.';
            footer.appendChild(note);

            // Как поставить расписание на домашний экран телефона.
            var install = document.createElement('p');
            install.className = 'mt-1.5';
            install.innerHTML =
                '<a class="font-medium text-sky-700 underline decoration-sky-300 ' +
                'underline-offset-2 hover:text-sky-900" href="install.html">' +
                'Как установить приложение на телефон</a>';
            footer.appendChild(install);
        }
    }

    function init() {
        checkTailwind();
        readUrlState();

        if (IS_STATIC) {
            setupStaticMode();
            registerServiceWorker();
        }

        el.refreshBtn.addEventListener('click', function () {
            fetchSchedule({ refresh: true });
        });

        el.errorRetry.addEventListener('click', function () {
            fetchSchedule({ refresh: true });
        });

        // Стрелки: сдвиг окна на один день назад/вперёд
        el.prevDay.addEventListener('click', function () {
            goToDate(isoShift(state.start, -1));
        });

        el.nextDay.addEventListener('click', function () {
            goToDate(isoShift(state.start, 1));
        });

        // Быстрые переходы: вчера / сегодня / завтра / через неделю
        el.quickChips.addEventListener('click', function (event) {
            var btn = event.target.closest('[data-offset]');
            if (!btn) return;
            var offset = parseInt(btn.dataset.offset, 10);
            goToDate(offset === 0 ? todayIso() : isoShift(todayIso(), offset));
        });

        // Сколько дней показывать: 1 / 3 / 7
        el.daysSwitch.addEventListener('click', function (event) {
            var btn = event.target.closest('[data-days]');
            if (!btn) return;
            var days = parseInt(btn.dataset.days, 10);
            if (days === state.days) return;
            state.days = days;
            state.loadedOnce = false;
            fetchSchedule({});
        });

        // Выбор даты в календаре
        el.dateInput.addEventListener('change', function () {
            var value = (el.dateInput.value || '').trim();
            if (value) goToDate(value);
        });

        // Тема: авто → светлая → тёмная
        if (el.themeBtn) {
            el.themeBtn.addEventListener('click', cycleTheme);
        }
        applyTheme(readThemeMode(), { silent: true, skipRotation: true });

        // Если страница открыта долго, «авто» само переключится в 20:00 и в 7:00.
        window.setInterval(function () {
            if (state.themeMode === 'auto') {
                applyTheme('auto', { silent: true });
            }
        }, 5 * 60 * 1000);

        el.groupInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                applyGroup();
            }
        });

        el.groupInput.addEventListener('blur', function () {
            var value = (el.groupInput.value || '').trim();
            if (value && value !== state.group) applyGroup();
        });

        el.groupInput.addEventListener('focus', loadGroupOptions);
        el.groupInput.addEventListener('input', loadGroupOptions);

        el.errorSuggestions.addEventListener('click', function (event) {
            var button = event.target.closest('button[data-group]');
            if (!button) return;
            state.group = button.dataset.group;
            el.groupInput.value = state.group;
            state.loadedOnce = false;
            fetchSchedule({ refresh: true });
        });

        if (window.location.protocol === 'file:') {
            showError(new Error('Страница открыта как файл. Запустите app.py и откройте http://127.0.0.1:5000/'));
        } else {
            fetchSchedule({});
        }

        window.setInterval(function () {
            if (!document.hidden) fetchSchedule({ silent: true });
        }, cfg.autoRefreshMs);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
