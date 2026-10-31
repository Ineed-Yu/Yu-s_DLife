// Acorn Club（/acorn-club/）の表示処理
// 1. 幕開け：葉っぱの幕が左右に開いて Acorn Club が現れる（このタブで初回だけ・動きを減らす設定なら出さない）
// 2. タブは「クラリス年表」「グッズ」「パーク」の3つ。
//    クラリス年表：/acorn-club/history.json（プロフィールと、作品・各パークでの登場の歴史。出典つき）を西暦順に表示し、パークで絞り込む
//    グッズ・パーク：/acorn-club/news.json を分け、種類と年で絞り込んで表示。パークは「ショー」「パレード」「グリーティング」「特別イベント」
//    情報の言語はページ上部の言語切替（JP/EN/FR/ZH）に合わせる（その言語の情報がまだ無いときは全言語を表示）
// 4. 公式サイト/アカウント一覧：日本・アメリカ・ハワイ・フランス・中国・香港のリージョンごとに切り替えて表示
// 3. X の投稿：最初はリンクだけ。利用者が「X の投稿を表示する」を押したときだけ X の公式の埋め込みを読み込む
// 文字はすべて textContent で入れ、HTML として解釈させない。リンクは http / https だけ。
(function () {
    'use strict';

    // ---------- 言語切替（他のページと同じ仕組み） ----------
    const SUPPORTED_LANGS = ['ja', 'en', 'fr', 'zh'];
    const normalizeLanguage = lang => (SUPPORTED_LANGS.includes(lang) ? lang : 'ja');
    let currentLang = 'ja';

    function getSavedLanguage() {
        try {
            return normalizeLanguage(localStorage.getItem('selectedLanguage'));
        } catch (e) {
            return 'ja';
        }
    }

    function switchLanguage(lang) {
        currentLang = normalizeLanguage(lang);
        try {
            localStorage.setItem('selectedLanguage', currentLang);
        } catch (e) {}
        document.querySelectorAll('[data-ja]').forEach(el => {
            el.textContent = el.getAttribute('data-' + currentLang) || el.getAttribute('data-ja');
        });
        document.querySelectorAll('.nav-link').forEach(link => {
            const url = link.getAttribute(`data-url-${currentLang}`);
            if (url) link.href = url;
        });
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === currentLang);
        });
        render();
    }

    // ---------- 画面の文言 ----------
    const T = {
        all: { ja: 'すべて', en: 'All', fr: 'Tout', zh: '全部' },
        pin: { ja: 'ピンバッジ', en: 'Pins', fr: "Pin's", zh: '徽章' },
        plush: { ja: 'ぬいぐるみ', en: 'Plush', fr: 'Peluches', zh: '毛绒玩偶' },
        goods: { ja: 'グッズ', en: 'Merchandise', fr: 'Produits', zh: '周边' },
        other: { ja: 'その他', en: 'Other', fr: 'Autres', zh: '其他' },
        greeting: { ja: 'グリーティング', en: 'Greetings', fr: 'Rencontres', zh: '见面会' },
        show: { ja: 'ショー', en: 'Shows', fr: 'Spectacles', zh: '表演' },
        parade: { ja: 'パレード', en: 'Parades', fr: 'Parades', zh: '巡游' },
        event: { ja: '特別イベント', en: 'Special events', fr: 'Événements spéciaux', zh: '特别活动' },
        work: { ja: '作品', en: 'Works', fr: 'Œuvres', zh: '作品' },
        view_history: { ja: 'クラリス年表', en: 'Clarice timeline', fr: 'Chronologie de Clarice', zh: '克拉丽丝年表' },
        profile: { ja: 'プロフィール', en: 'Profile', fr: 'Profil', zh: '简介' },
        source: { ja: '出典', en: 'Source', fr: 'Source', zh: '出处' },
        allParks: { ja: 'すべてのパーク・作品', en: 'All parks and works', fr: 'Tous les parcs et œuvres', zh: '全部乐园与作品' },
        park_film: { ja: '作品（映画・シリーズ）', en: 'Films and series', fr: 'Films et séries', zh: '电影与剧集' },
        park_tdl: { ja: '東京ディズニーランド', en: 'Tokyo Disneyland', fr: 'Tokyo Disneyland', zh: '东京迪士尼乐园' },
        park_tds: { ja: '東京ディズニーシー', en: 'Tokyo DisneySea', fr: 'Tokyo DisneySea', zh: '东京迪士尼海洋' },
        park_dl: { ja: 'ディズニーランド・リゾート（カリフォルニア）', en: 'Disneyland Resort (California)', fr: 'Disneyland Resort (Californie)', zh: '迪士尼乐园度假区（加州）' },
        park_wdw: { ja: 'ウォルト・ディズニー・ワールド', en: 'Walt Disney World', fr: 'Walt Disney World', zh: '华特迪士尼世界' },
        park_dlp: { ja: 'ディズニーランド・パリ', en: 'Disneyland Paris', fr: 'Disneyland Paris', zh: '巴黎迪士尼乐园' },
        park_shdl: { ja: '上海ディズニーリゾート', en: 'Shanghai Disney Resort', fr: 'Shanghai Disney Resort', zh: '上海迪士尼度假区' },
        park_hkdl: { ja: '香港ディズニーランド', en: 'Hong Kong Disneyland', fr: 'Hong Kong Disneyland', zh: '香港迪士尼乐园' },
        park_aulani: { ja: 'アウラニ（ハワイ）', en: 'Aulani (Hawaii)', fr: 'Aulani (Hawaï)', zh: '奥拉尼（夏威夷）' },
        historyError: {
            ja: '年表を読み込めませんでした。通信状況を確認して、ページを再読み込みしてください。',
            en: "The timeline couldn't be loaded. Check your connection and reload the page.",
            fr: 'Impossible de charger la chronologie. Vérifiez votre connexion et rechargez la page.',
            zh: '无法加载年表。请检查网络连接后重新加载页面。'
        },
        view_goods: { ja: 'グッズ', en: 'Merchandise', fr: 'Produits', zh: '周边' },
        view_appear: { ja: 'パーク', en: 'Parks', fr: 'Parcs', zh: '乐园' },
        region_jp: { ja: '日本', en: 'Japan', fr: 'Japon', zh: '日本' },
        region_us: { ja: 'アメリカ', en: 'USA', fr: 'États-Unis', zh: '美国' },
        region_fr: { ja: 'フランス', en: 'France', fr: 'France', zh: '法国' },
        region_hi: { ja: 'ハワイ', en: 'Hawaii', fr: 'Hawaï', zh: '夏威夷' },
        region_cn: { ja: '中国', en: 'China', fr: 'Chine', zh: '中国' },
        region_hk: { ja: '香港', en: 'Hong Kong', fr: 'Hong Kong', zh: '香港' },
        regionLabel: { ja: 'リージョンを選ぶ', en: 'Choose a region', fr: 'Choisir une région', zh: '选择地区' },
        langFallback: {
            ja: '日本語の情報がまだないため、すべての言語の情報を表示しています。',
            en: 'There is no news in English here yet, so news in all languages is shown.',
            fr: 'Pas encore de nouvelles en français ici : les informations de toutes les langues sont affichées.',
            zh: '这里暂时没有中文信息，因此显示所有语言的信息。'
        },
        viewLabel: { ja: '表示する情報', en: 'What to show', fr: 'Informations affichées', zh: '显示内容' },
        xPost: { ja: 'X の投稿', en: 'Post on X', fr: 'Publication sur X', zh: 'X 上的帖子' },
        xShow: { ja: 'X の投稿を表示する', en: 'Show posts from X', fr: 'Afficher les publications X', zh: '显示 X 帖子' },
        xHide: { ja: 'X の投稿をリンクだけにする', en: 'Show X posts as links only', fr: 'Liens seulement pour X', zh: 'X 帖子仅显示链接' },
        xNote: {
            ja: '表示すると X（旧 Twitter）のサービスに接続し、画像付きで投稿を表示します。',
            en: 'Showing posts connects to X (formerly Twitter) and displays them with images.',
            fr: 'L’affichage se connecte à X (ex-Twitter) et montre les publications avec leurs images.',
            zh: '显示时将连接 X（原 Twitter）服务，并带图片显示帖子。'
        },
        allYears: { ja: 'すべての年', en: 'All years', fr: 'Toutes les années', zh: '全部年份' },
        kindLabel: { ja: '種類で絞り込む', en: 'Filter by type', fr: 'Filtrer par type', zh: '按类型筛选' },
        official: { ja: '公式', en: 'Official', fr: 'Officiel', zh: '官方' },
        added: { ja: '手動で追加', en: 'Added by hand', fr: 'Ajouté à la main', zh: '手动添加' },
        opens: { ja: '（別のサイトが開きます）', en: ' (opens another site)', fr: ' (ouvre un autre site)', zh: '（将打开其他网站）' },
        more: { ja: 'さらに表示', en: 'Show more', fr: 'Afficher plus', zh: '显示更多' },
        empty: {
            ja: 'まだ新着情報がありません。しばらくしてからもう一度ご覧ください。',
            en: 'No news yet. Please check back later.',
            fr: 'Pas encore de nouvelles. Revenez un peu plus tard.',
            zh: '暂时没有新消息。请稍后再来看看。'
        },
        noMatch: {
            ja: 'この絞り込みに当てはまる情報はまだありません。「すべて」に戻すと全件を表示します。',
            en: 'Nothing matches this filter yet. Choose “All” to see everything.',
            fr: 'Rien ne correspond encore à ce filtre. Choisissez « Tout » pour tout afficher.',
            zh: '暂无符合筛选条件的信息。选择“全部”即可查看所有内容。'
        },
        loadError: {
            ja: '情報を読み込めませんでした。通信状況を確認して、ページを再読み込みしてください。',
            en: "The news couldn't be loaded. Check your connection and reload the page.",
            fr: "Impossible de charger les informations. Vérifiez votre connexion et rechargez la page.",
            zh: '无法加载信息。请检查网络连接后重新加载页面。'
        }
    };
    const t = key => (T[key] && (T[key][currentLang] || T[key].ja)) || key;

    // ---------- データ ----------
    let data = null;      // { items: [...], links: [...] }
    let failed = false;
    const GOODS = ['pin', 'plush', 'goods', 'other'];
    const APPEAR = ['show', 'parade', 'greeting', 'event'];
    const VIEWS = ['history', 'goods', 'appear'];
    const PARKS = ['film', 'tdl', 'tds', 'dl', 'wdw', 'dlp', 'shdl', 'hkdl', 'aulani'];
    let chron = null;     // クラリス年表（/acorn-club/history.json）
    let historyFailed = false;
    let historyPark = 'all';
    const viewOf = item => (APPEAR.includes(item.category) ? 'appear' : 'goods');
    const state = { view: 'goods', category: 'all', year: 'all', limit: 40 };
    const REGIONS = ['jp', 'us', 'hi', 'fr', 'cn', 'hk'];
    const REGION_OF_LANG = { ja: 'jp', en: 'us', fr: 'fr', zh: 'cn' };
    let region = null;    // 利用者が選んだリージョン（選ぶまではページの言語に合わせる）
    let xEmbed = false;
    try {
        xEmbed = localStorage.getItem('acornXEmbed') === '1';
    } catch (e) {}
    try {
        const v = new URLSearchParams(location.search).get('view');
        if (v === 'park' || v === 'appear') state.view = 'appear';
        if (v === 'history') state.view = 'history';
    } catch (e) {}
    const yearOf = item => String(item.date || '').slice(0, 4);

    function safeUrl(url) {
        try {
            const u = new URL(String(url));
            return (u.protocol === 'https:' || u.protocol === 'http:') ? u.href : null;
        } catch (e) {
            return null;
        }
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    const LOCALES = { ja: 'ja-JP', en: 'en-US', fr: 'fr-FR', zh: 'zh-CN' };
    function monthLabel(d) {
        return new Intl.DateTimeFormat(LOCALES[currentLang], { year: 'numeric', month: 'long' }).format(d);
    }
    function dayLabel(d) {
        return new Intl.DateTimeFormat(LOCALES[currentLang], { month: 'short', day: 'numeric' }).format(d);
    }

    // ---------- 絞り込みボタン ----------
    function chip(label, pressed, onClick) {
        const b = el('button', 'filter-chip', label);
        b.type = 'button';
        b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
        b.addEventListener('click', onClick);
        return b;
    }

    // 「クラリス年表」「グッズ」「パーク」の切り替え（タブ）
    function renderViews() {
        const box = document.getElementById('club-views');
        if (!box) return;
        box.setAttribute('aria-label', t('viewLabel'));
        box.replaceChildren();
        VIEWS.forEach(v => {
            const b = el('button', 'view-tab', t('view_' + v));
            b.type = 'button';
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-selected', state.view === v ? 'true' : 'false');
            b.setAttribute('aria-controls', 'timeline-list');
            b.addEventListener('click', () => {
                if (state.view === v) return;
                state.view = v;
                Object.assign(state, { category: 'all', year: 'all', limit: 40 });
                try {
                    const q = new URLSearchParams(location.search);
                    if (v === 'appear') q.set('view', 'park');
                    else if (v === 'history') q.set('view', 'history');
                    else q.delete('view');
                    window.history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : ''));
                } catch (e) {}
                render();
            });
            box.appendChild(b);
        });
    }

    // X の投稿の埋め込み（押したときだけ X のスクリプトを読み込む）
    function renderXToggle(items) {
        const box = document.getElementById('x-embed');
        if (!box) return;
        const hasX = items.some(i => i.origin === 'x');
        box.hidden = !hasX;
        if (!hasX) return;
        box.replaceChildren();
        const b = el('button', 'filter-chip x-toggle', xEmbed ? t('xHide') : t('xShow'));
        b.type = 'button';
        b.setAttribute('aria-pressed', xEmbed ? 'true' : 'false');
        b.addEventListener('click', () => {
            xEmbed = !xEmbed;
            try {
                localStorage.setItem('acornXEmbed', xEmbed ? '1' : '0');
            } catch (e) {}
            render();
        });
        box.appendChild(b);
        box.appendChild(el('p', 'x-note', t('xNote')));
    }

    let xScript = null;
    function loadXWidgets(container) {
        const run = () => window.twttr && window.twttr.widgets && window.twttr.widgets.load(container);
        if (window.twttr && window.twttr.widgets) return run();
        if (!xScript) {
            xScript = document.createElement('script');
            xScript.src = 'https://platform.twitter.com/widgets.js';
            xScript.async = true;
            xScript.charset = 'utf-8';
            document.head.appendChild(xScript);
        }
        xScript.addEventListener('load', run, { once: true });
    }

    function renderFilters(items) {
        const catRow = document.getElementById('filter-category');
        if (!catRow) return;
        catRow.setAttribute('aria-label', t('kindLabel'));
        if (state.category !== 'all' && state.view !== 'appear' && !items.some(i => i.category === state.category)) state.category = 'all';
        catRow.replaceChildren(chip(t('all'), state.category === 'all', () => setState({ category: 'all' })));
        (state.view === 'appear' ? APPEAR : GOODS).forEach(c => {
            // パークの4つ（ショー・パレード・グリーティング・特別イベント）は、情報が無くても常に並べる
            if (state.view === 'appear' || items.some(i => i.category === c)) {
                catRow.appendChild(chip(t(c), state.category === c, () => setState({ category: c })));
            }
        });
        catRow.hidden = items.length === 0;
        // 年（西暦）：情報がある年だけを新しい順に、プルダウンで選ぶ
        const yearBox = document.getElementById('filter-year');
        const select = document.getElementById('year-select');
        if (yearBox && select) {
            const years = [...new Set(items.map(yearOf).filter(y => /^\d{4}$/.test(y)))].sort().reverse();
            if (state.year !== 'all' && !years.includes(state.year)) state.year = 'all';
            select.replaceChildren();
            const all = el('option', '', t('allYears'));
            all.value = 'all';
            select.appendChild(all);
            years.forEach(y => {
                const o = el('option', '', y);
                o.value = y;
                select.appendChild(o);
            });
            select.value = state.year;
            yearBox.hidden = years.length === 0;
        }
    }

    function setState(next) {
        Object.assign(state, next, { limit: 40 });
        render();
    }

    // ---------- タイムライン ----------
    // 記事の画像（1件に1枚）：掲載元が共有用に指定した画像を、掲載元の場所のまま表示する。
    // 画像が無い・読み込めないときは、どんぐりの印（このサイトのオリジナル）を代わりに表示する。
    function acornPlaceholder() {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'playbill-thumb-mark');
        svg.setAttribute('aria-hidden', 'true');
        const use = document.createElementNS(ns, 'use');
        use.setAttribute('href', '#acorn-mark');
        svg.appendChild(use);
        return svg;
    }

    function thumb(item) {
        const box = el('span', 'playbill-thumb');
        const src = String(item.image || '');
        if (/^https:\/\//.test(src) && safeUrl(src)) {
            const img = document.createElement('img');
            img.alt = '';
            img.loading = 'lazy';
            img.decoding = 'async';
            img.referrerPolicy = 'no-referrer';
            img.addEventListener('error', () => {
                box.classList.add('is-empty');
                img.replaceWith(acornPlaceholder());
            }, { once: true });
            img.src = src;
            box.appendChild(img);
        } else {
            box.classList.add('is-empty');
            box.appendChild(acornPlaceholder());
        }
        return box;
    }

    function playbill(item) {
        const url = safeUrl(item.url);
        const li = el('li', 'timeline-item');
        li.dataset.category = item.category;
        const card = el(url ? 'a' : 'div', 'playbill');
        if (url) {
            card.href = url;
            card.target = '_blank';
            card.rel = 'noopener noreferrer';
        }
        card.appendChild(thumb(item));
        const body = el('span', 'playbill-body');
        card.appendChild(body);
        const head = el('span', 'playbill-head');
        const d = new Date(item.date);
        const time = el('time', 'playbill-date', isNaN(d) ? '' : dayLabel(d));
        if (!isNaN(d)) time.dateTime = item.date;
        head.appendChild(time);
        head.appendChild(el('span', 'playbill-kind', t(item.category)));
        body.appendChild(head);
        const isX = item.origin === 'x' && /^\d+$/.test(String(item.tweet || ''));
        const title = el('span', 'playbill-title', isX ? t('xPost') : (item.title || ''));
        if (item.lang && item.lang !== 'ja') title.lang = item.lang === 'zh' ? 'zh' : item.lang;
        body.appendChild(title);
        const source = el('span', 'playbill-source', item.source || '');
        if (item.official) source.appendChild(el('span', 'playbill-official', t('official')));
        if (item.origin === 'manual') source.appendChild(document.createTextNode(`（${t('added')}）`));
        source.appendChild(el('span', 'visually-hidden', t('opens')));
        body.appendChild(source);
        li.appendChild(card);
        if (isX && xEmbed) {
            // X の公式の埋め込み（文字・画像は X が表示し、投稿が消されれば表示されなくなる）
            const quote = el('blockquote', 'twitter-tweet');
            quote.dataset.dnt = 'true';
            quote.dataset.lang = currentLang === 'zh' ? 'zh-cn' : currentLang;
            const a = el('a', '', t('xPost'));
            a.href = `https://twitter.com/i/status/${item.tweet}`;
            quote.appendChild(a);
            const wrap = el('div', 'x-embed-wrap');
            wrap.appendChild(quote);
            li.appendChild(wrap);
            li.classList.add('has-embed');
        }
        return li;
    }

    // 情報の言語：ページの言語に合わせる。その言語の情報がこの切り替え（グッズ／パーク）に1件も無いときは全言語
    function byPageLanguage(items) {
        const mine = items.filter(i => i.lang === currentLang);
        return { items: mine.length ? mine : items, fallback: mine.length === 0 && items.length > 0 };
    }

    // 年表と、グッズ・パークのタイムラインで、使う部品を切り替える
    function showSections() {
        const isHistory = state.view === 'history';
        const toggle = (id, hidden) => {
            const node = document.getElementById(id);
            if (node) node.hidden = hidden;
        };
        toggle('history', !isHistory);
        toggle('timeline', isHistory);
        toggle('filter-park', !isHistory || !chron || !chron.entries.length);
        if (isHistory) {
            toggle('filter-category', true);
            toggle('filter-year', true);
            toggle('x-embed', true);
        }
    }

    // ---------- クラリス年表 ----------
    const loc = o => (o && typeof o === 'object' ? (o[currentLang] || o.en || o.ja || '') : String(o || ''));

    function historyDate(date) {
        const m = String(date || '').match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/);
        if (!m) return { year: '', label: '' };
        if (!m[2]) return { year: m[1], label: '' };
        const d = new Date(Date.UTC(+m[1], +m[2] - 1, +(m[3] || 1)));
        const opts = m[3] ? { month: 'short', day: 'numeric', timeZone: 'UTC' } : { month: 'long', timeZone: 'UTC' };
        return { year: m[1], label: new Intl.DateTimeFormat(LOCALES[currentLang], opts).format(d) };
    }

    function sourceLink(src) {
        const url = safeUrl(src && src.url);
        if (!url) return null;
        const a = el('a', 'history-source', `${t('source')}：${loc(src.name) || url}`);
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.appendChild(el('span', 'visually-hidden', t('opens')));
        return a;
    }

    function renderHistory() {
        const prof = document.getElementById('history-profile');
        const list = document.getElementById('history-list');
        const empty = document.getElementById('history-empty');
        if (!prof || !list || !empty) return;
        if (!chron) {
            prof.replaceChildren();
            list.replaceChildren();
            empty.hidden = !historyFailed;
            empty.textContent = t('historyError');
            if (!historyFailed) loadHistory();
            return;
        }
        // プロフィール
        prof.replaceChildren();
        const p = chron.profile;
        if (p) {
            const card = el('div', 'playbill history-card');
            card.appendChild(el('h3', 'history-card-title', `${t('profile')}｜${loc(p.name)}`));
            const dl = el('dl', 'history-facts');
            (p.items || []).forEach(it => {
                dl.appendChild(el('dt', '', loc(it.label)));
                dl.appendChild(el('dd', '', loc(it.value)));
            });
            card.appendChild(dl);
            const srcs = el('p', 'history-sources');
            (p.sources || []).forEach(src => {
                const a = sourceLink(src);
                if (a) srcs.appendChild(a);
            });
            card.appendChild(srcs);
            prof.appendChild(card);
        }
        // パークの絞り込み（登録があるパークだけ）
        const select = document.getElementById('park-select');
        const parks = PARKS.filter(k => chron.entries.some(e => e.park === k));
        if (historyPark !== 'all' && !parks.includes(historyPark)) historyPark = 'all';
        if (select) {
            select.replaceChildren();
            [['all', t('allParks')], ...parks.map(k => [k, t('park_' + k)])].forEach(([v, label]) => {
                const o = el('option', '', label);
                o.value = v;
                select.appendChild(o);
            });
            select.value = historyPark;
        }
        // 年表（古い順。西暦ごとに見出し）
        const shown = chron.entries
            .filter(e => historyPark === 'all' || e.park === historyPark)
            .sort((a, b) => String(a.date).localeCompare(String(b.date)));
        list.replaceChildren();
        let year = '';
        shown.forEach(e => {
            const d = historyDate(e.date);
            if (d.year && d.year !== year) {
                year = d.year;
                list.appendChild(el('li', 'timeline-month', year));
            }
            const li = el('li', 'timeline-item');
            li.dataset.category = e.kind === 'work' ? 'work' : e.kind;
            const card = el('div', 'playbill history-entry');
            const head = el('span', 'playbill-head');
            if (d.label) head.appendChild(el('span', 'playbill-date', d.label));
            head.appendChild(el('span', 'playbill-kind', t(e.kind)));
            head.appendChild(el('span', 'history-park', t('park_' + e.park)));
            card.appendChild(head);
            card.appendChild(el('span', 'playbill-title', loc(e.title)));
            if (loc(e.note)) card.appendChild(el('span', 'history-note', loc(e.note)));
            const a = sourceLink(e.source);
            if (a) card.appendChild(a);
            li.appendChild(card);
            list.appendChild(li);
        });
        empty.hidden = shown.length > 0;
        if (!shown.length) empty.textContent = t('noMatch');
    }

    let historyLoading = false;
    function loadHistory() {
        if (historyLoading) return;
        historyLoading = true;
        fetch('/acorn-club/history.json', { cache: 'no-cache' })
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(json => {
                chron = {
                    profile: json.profile || null,
                    entries: (Array.isArray(json.entries) ? json.entries : []).filter(e => e && e.title && PARKS.includes(e.park))
                };
                render();
            })
            .catch(err => {
                console.error('クラリス年表を読み込めませんでした:', err);
                historyFailed = true;
                render();
            });
    }

    function render() {
        const list = document.getElementById('timeline-list');
        const empty = document.getElementById('timeline-empty');
        if (!list || !empty) return;
        renderViews();
        showSections();
        if (state.view === 'history') {
            renderHistory();
            renderLinks();
            return;
        }
        if (failed) {
            list.replaceChildren();
            empty.textContent = t('loadError');
            empty.hidden = false;
            return;
        }
        if (!data) return;
        renderXToggle(data.items);
        const picked = byPageLanguage(data.items.filter(i => viewOf(i) === state.view));
        const items = picked.items;
        const note = document.getElementById('lang-note');
        if (note) {
            note.textContent = t('langFallback');
            note.hidden = !picked.fallback;
        }
        renderFilters(items);
        const shown = items.filter(i =>
            (state.category === 'all' || i.category === state.category) &&
            (state.year === 'all' || yearOf(i) === state.year));
        list.replaceChildren();
        let month = '';
        shown.slice(0, state.limit).forEach(item => {
            const d = new Date(item.date);
            const m = isNaN(d) ? '' : monthLabel(d);
            if (m && m !== month) {
                month = m;
                list.appendChild(el('li', 'timeline-month', m));
            }
            list.appendChild(playbill(item));
        });
        if (shown.length > state.limit) {
            const li = el('li');
            const more = el('button', 'filter-chip timeline-more', t('more'));
            more.type = 'button';
            more.addEventListener('click', () => { state.limit += 40; render(); });
            li.appendChild(more);
            list.appendChild(li);
        }
        empty.hidden = shown.length > 0;
        empty.textContent = items.length === 0 ? t('empty') : t('noMatch');
        if (xEmbed && list.querySelector('.twitter-tweet')) loadXWidgets(list);
        renderLinks();
    }

    // 公式サイト/アカウント一覧：リージョン（日本・アメリカ・ハワイ・フランス・中国・香港）を選ぶと、その地域の一覧を表示
    function renderLinks() {
        const ul = document.getElementById('sources-list');
        const tabs = document.getElementById('sources-regions');
        if (!ul || !data) return;
        const links = (data.links || []).filter(l => safeUrl(l.url) && REGIONS.includes(l.region));
        const available = REGIONS.filter(r => links.some(l => l.region === r));
        let current = region || REGION_OF_LANG[currentLang];
        if (!available.includes(current)) current = available[0];
        if (tabs) {
            tabs.setAttribute('aria-label', t('regionLabel'));
            tabs.replaceChildren();
            available.forEach(r => {
                const b = el('button', 'region-tab', t('region_' + r));
                b.type = 'button';
                b.setAttribute('aria-pressed', r === current ? 'true' : 'false');
                b.setAttribute('aria-controls', 'sources-list');
                b.addEventListener('click', () => {
                    region = r;
                    renderLinks();
                });
                tabs.appendChild(b);
            });
            tabs.hidden = available.length === 0;
        }
        ul.replaceChildren();
        links.filter(l => l.region === current).forEach(link => {
            const url = safeUrl(link.url);
            const li = el('li');
            const a = el('a', '', (link.name && (link.name[currentLang] || link.name.en || link.name.ja)) || url);
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.appendChild(el('span', 'visually-hidden', t('opens')));
            li.appendChild(a);
            ul.appendChild(li);
        });
    }

    function load() {
        fetch('/acorn-club/news.json', { cache: 'no-cache' })
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(json => {
                data = {
                    items: (Array.isArray(json.items) ? json.items : [])
                        .filter(i => i && (i.title || i.origin === 'x') && safeUrl(i.url)),
                    links: Array.isArray(json.links) ? json.links : []
                };
                render();
            })
            .catch(err => {
                console.error('Acorn Club の情報を読み込めませんでした:', err);
                failed = true;
                render();
            });
    }

    // ---------- 幕開け ----------
    // 動き自体は CSS だけで進む（ページの表示と同時に始まり、スクリプトの読み込みを待たない）。
    // ここでは、終わったあとに幕を取り除くことと「スキップ」だけを受け持つ。
    function openCurtain() {
        const root = document.documentElement;
        const curtain = document.getElementById('acorn-curtain');
        if (!root.classList.contains('acorn-intro') || !curtain) return;
        try {
            sessionStorage.setItem('acornCurtainSeen', '1');
        } catch (e) {}
        let done = false;
        const finish = () => {
            if (done) return;
            done = true;
            root.classList.remove('acorn-intro');
            curtain.remove();
        };
        curtain.addEventListener('animationend', e => {
            if (e.target === curtain) finish();
        });
        setTimeout(finish, 4000); // 念のため（動きが止められた環境でも必ず消える）
        const skip = document.getElementById('acorn-skip');
        if (skip) {
            skip.tabIndex = 0;
            skip.addEventListener('click', () => {
                curtain.classList.add('is-skipping');
                setTimeout(finish, 260);
            });
        }
    }

    // 幕は、ページの部品がそろったらすぐに準備する（この script は本文の最後にある）
    openCurtain();

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => switchLanguage(btn.dataset.lang));
        });
        const saved = getSavedLanguage();
        if (saved !== 'ja') switchLanguage(saved);
        const parkSelect = document.getElementById('park-select');
        if (parkSelect) parkSelect.addEventListener('change', () => { historyPark = parkSelect.value; render(); });
        const yearSelect = document.getElementById('year-select');
        if (yearSelect) yearSelect.addEventListener('change', () => setState({ year: yearSelect.value }));
        load();
    });
})();
