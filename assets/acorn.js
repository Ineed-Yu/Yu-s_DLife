// Acorn Club（/acorn-club/）の表示処理
// 1. 幕開け：葉っぱの幕が左右に開いて Acorn Club が現れる（このタブで初回だけ・動きを減らす設定なら出さない）
// 2. タイムライン：/acorn-club/news.json を「グッズ・新商品」「グリーティング・ショー」に分け、種類・年・言語で絞り込んで表示
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
        event: { ja: 'イベント', en: 'Events', fr: 'Événements', zh: '活动' },
        view_goods: { ja: 'グッズ・新商品', en: 'Merchandise', fr: 'Produits', zh: '周边新品' },
        view_appear: { ja: 'グリーティング・ショー', en: 'Greetings & shows', fr: 'Rencontres et spectacles', zh: '见面会与表演' },
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
        allLang: { ja: 'すべての言語', en: 'All languages', fr: 'Toutes les langues', zh: '所有语言' },
        lang_ja: { ja: '日本語の情報', en: 'In Japanese', fr: 'En japonais', zh: '日语' },
        lang_en: { ja: '英語の情報', en: 'In English', fr: 'En anglais', zh: '英语' },
        lang_zh: { ja: '中国語の情報', en: 'In Chinese', fr: 'En chinois', zh: '中文' },
        lang_fr: { ja: 'フランス語の情報', en: 'In French', fr: 'En français', zh: '法语' },
        allYears: { ja: 'すべての年', en: 'All years', fr: 'Toutes les années', zh: '全部年份' },
        yearLabel: { ja: '年で絞り込む', en: 'Filter by year', fr: 'Filtrer par année', zh: '按年份筛选' },
        kindLabel: { ja: '種類で絞り込む', en: 'Filter by type', fr: 'Filtrer par type', zh: '按类型筛选' },
        langLabel: { ja: '言語で絞り込む', en: 'Filter by language', fr: 'Filtrer par langue', zh: '按语言筛选' },
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
    const APPEAR = ['greeting', 'show', 'parade', 'event'];
    const viewOf = item => (APPEAR.includes(item.category) ? 'appear' : 'goods');
    const state = { view: 'goods', category: 'all', lang: 'all', year: 'all', limit: 40 };
    let xEmbed = false;
    try {
        xEmbed = localStorage.getItem('acornXEmbed') === '1';
    } catch (e) {}
    try {
        if (new URLSearchParams(location.search).get('view') === 'appear') state.view = 'appear';
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

    // 「グッズ・新商品」「グリーティング・ショー」の切り替え（タブ）
    function renderViews() {
        const box = document.getElementById('club-views');
        if (!box) return;
        box.setAttribute('aria-label', t('viewLabel'));
        box.replaceChildren();
        ['goods', 'appear'].forEach(v => {
            const b = el('button', 'view-tab', t('view_' + v));
            b.type = 'button';
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-selected', state.view === v ? 'true' : 'false');
            b.setAttribute('aria-controls', 'timeline-list');
            b.addEventListener('click', () => {
                if (state.view === v) return;
                state.view = v;
                Object.assign(state, { category: 'all', year: 'all', lang: 'all', limit: 40 });
                try {
                    const q = new URLSearchParams(location.search);
                    if (v === 'appear') q.set('view', 'appear'); else q.delete('view');
                    history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : ''));
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
        const langRow = document.getElementById('filter-lang');
        if (!catRow || !langRow) return;
        catRow.setAttribute('aria-label', t('kindLabel'));
        langRow.setAttribute('aria-label', t('langLabel'));
        catRow.replaceChildren(chip(t('all'), state.category === 'all', () => setState({ category: 'all' })));
        (state.view === 'appear' ? APPEAR : GOODS).forEach(c => {
            if (items.some(i => i.category === c)) {
                catRow.appendChild(chip(t(c), state.category === c, () => setState({ category: c })));
            }
        });
        // 年（西暦）：情報がある年だけ、新しい順に並べる
        const yearRow = document.getElementById('filter-year');
        if (yearRow) {
            const years = [...new Set(items.map(yearOf).filter(y => /^\d{4}$/.test(y)))].sort().reverse();
            yearRow.setAttribute('aria-label', t('yearLabel'));
            yearRow.replaceChildren();
            if (years.length) {
                yearRow.appendChild(chip(t('allYears'), state.year === 'all', () => setState({ year: 'all' })));
                years.forEach(y => yearRow.appendChild(chip(y, state.year === y, () => setState({ year: y }))));
            }
            yearRow.hidden = years.length === 0;
        }
        // 言語：情報がある言語だけ
        const langs = ['ja', 'en', 'zh', 'fr'].filter(l => items.some(i => i.lang === l));
        langRow.replaceChildren();
        if (langs.length > 1) {
            langRow.appendChild(chip(t('allLang'), state.lang === 'all', () => setState({ lang: 'all' })));
            langs.forEach(l => langRow.appendChild(chip(t('lang_' + l), state.lang === l, () => setState({ lang: l }))));
        }
        catRow.hidden = items.length === 0;
    }

    function setState(next) {
        Object.assign(state, next, { limit: 40 });
        render();
    }

    // ---------- タイムライン ----------
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
        const head = el('span', 'playbill-head');
        const d = new Date(item.date);
        const time = el('time', 'playbill-date', isNaN(d) ? '' : dayLabel(d));
        if (!isNaN(d)) time.dateTime = item.date;
        head.appendChild(time);
        head.appendChild(el('span', 'playbill-kind', t(item.category)));
        card.appendChild(head);
        const isX = item.origin === 'x' && /^\d+$/.test(String(item.tweet || ''));
        const title = el('span', 'playbill-title', isX ? t('xPost') : (item.title || ''));
        if (item.lang && item.lang !== 'ja') title.lang = item.lang === 'zh' ? 'zh' : item.lang;
        card.appendChild(title);
        const source = el('span', 'playbill-source', item.source || '');
        if (item.official) source.appendChild(el('span', 'playbill-official', t('official')));
        if (item.origin === 'manual') source.appendChild(document.createTextNode(`（${t('added')}）`));
        source.appendChild(el('span', 'visually-hidden', t('opens')));
        card.appendChild(source);
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

    function render() {
        const list = document.getElementById('timeline-list');
        const empty = document.getElementById('timeline-empty');
        if (!list || !empty) return;
        if (failed) {
            list.replaceChildren();
            empty.textContent = t('loadError');
            empty.hidden = false;
            return;
        }
        if (!data) return;
        renderViews();
        renderXToggle(data.items);
        const items = data.items.filter(i => viewOf(i) === state.view);
        renderFilters(items);
        const shown = items.filter(i =>
            (state.category === 'all' || i.category === state.category) &&
            (state.lang === 'all' || i.lang === state.lang) &&
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

    function renderLinks() {
        const ul = document.getElementById('sources-list');
        if (!ul || !data) return;
        ul.replaceChildren();
        (data.links || []).forEach(link => {
            const url = safeUrl(link.url);
            if (!url) return;
            const li = el('li');
            const a = el('a', '', (link.name && (link.name[currentLang] || link.name.en || link.name.ja)) || url);
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
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
    function openCurtain() {
        const root = document.documentElement;
        const curtain = document.getElementById('acorn-curtain');
        if (!root.classList.contains('acorn-intro') || !curtain) return;
        try {
            sessionStorage.setItem('acornCurtainSeen', '1');
        } catch (e) {}
        const skip = document.getElementById('acorn-skip');
        let done = false;
        const finish = () => {
            if (done) return;
            done = true;
            root.classList.remove('acorn-intro');
            curtain.remove();
        };
        if (skip) {
            skip.tabIndex = 0;
            skip.addEventListener('click', finish);
        }
        // 葉がそよぐ → 看板が灯る → 幕が左右に開く → 消える
        setTimeout(() => curtain.classList.add('is-lit'), 450);
        setTimeout(() => curtain.classList.add('is-open'), 1500);
        setTimeout(finish, 2900);
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => switchLanguage(btn.dataset.lang));
        });
        const saved = getSavedLanguage();
        if (saved !== 'ja') switchLanguage(saved);
        openCurtain();
        load();
    });
})();
