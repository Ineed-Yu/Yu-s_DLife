// Acorn Club（/acorn-club/）の表示処理
// 1. 幕開け：葉っぱの幕が左右に開いて Acorn Club が現れる（このタブで初回だけ・動きを減らす設定なら出さない）
// 2. タイムライン：/acorn-club/news.json（tools/acorn_news.py が自動で集めたもの）を、種類・言語で絞り込んで表示
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
        allLang: { ja: 'すべての言語', en: 'All languages', fr: 'Toutes les langues', zh: '所有语言' },
        langJa: { ja: '日本語の情報', en: 'In Japanese', fr: 'En japonais', zh: '日语' },
        langEn: { ja: '英語の情報', en: 'In English', fr: 'En anglais', zh: '英语' },
        kindLabel: { ja: '種類で絞り込む', en: 'Filter by type', fr: 'Filtrer par type', zh: '按类型筛选' },
        langLabel: { ja: '言語で絞り込む', en: 'Filter by language', fr: 'Filtrer par langue', zh: '按语言筛选' },
        official: { ja: '公式', en: 'Official', fr: 'Officiel', zh: '官方' },
        added: { ja: '手動で追加', en: 'Added by hand', fr: 'Ajouté à la main', zh: '手动添加' },
        opens: { ja: '（別のサイトが開きます）', en: ' (opens another site)', fr: ' (ouvre un autre site)', zh: '（将打开其他网站）' },
        more: { ja: 'さらに表示', en: 'Show more', fr: 'Afficher plus', zh: '显示更多' },
        empty: {
            ja: 'まだ新着情報がありません。2時間ごとに自動で集めているので、しばらくしてからもう一度ご覧ください。',
            en: 'No news yet. New items are collected every two hours, so please check back later.',
            fr: "Pas encore de nouvelles. Les informations sont collectées toutes les deux heures : revenez un peu plus tard.",
            zh: '暂时没有新消息。每两小时自动收集一次，请稍后再来看看。'
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
    const state = { category: 'all', lang: 'all', limit: 40 };

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

    function renderFilters(items) {
        const catRow = document.getElementById('filter-category');
        const langRow = document.getElementById('filter-lang');
        if (!catRow || !langRow) return;
        catRow.setAttribute('aria-label', t('kindLabel'));
        langRow.setAttribute('aria-label', t('langLabel'));
        catRow.replaceChildren(chip(t('all'), state.category === 'all', () => setState({ category: 'all' })));
        ['pin', 'plush', 'goods', 'other'].forEach(c => {
            if (items.some(i => i.category === c)) {
                catRow.appendChild(chip(t(c), state.category === c, () => setState({ category: c })));
            }
        });
        const langs = new Set(items.map(i => i.lang));
        langRow.replaceChildren();
        if (langs.size > 1) {
            langRow.appendChild(chip(t('allLang'), state.lang === 'all', () => setState({ lang: 'all' })));
            langRow.appendChild(chip(t('langJa'), state.lang === 'ja', () => setState({ lang: 'ja' })));
            langRow.appendChild(chip(t('langEn'), state.lang === 'en', () => setState({ lang: 'en' })));
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
        const title = el('span', 'playbill-title', item.title || '');
        if (item.lang && item.lang !== 'ja') title.lang = item.lang;
        card.appendChild(title);
        const source = el('span', 'playbill-source', item.source || '');
        if (item.official) source.appendChild(el('span', 'playbill-official', t('official')));
        if (item.origin === 'manual') source.appendChild(document.createTextNode(`（${t('added')}）`));
        source.appendChild(el('span', 'visually-hidden', t('opens')));
        card.appendChild(source);
        li.appendChild(card);
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
        const items = data.items;
        renderFilters(items);
        const shown = items.filter(i =>
            (state.category === 'all' || i.category === state.category) &&
            (state.lang === 'all' || i.lang === state.lang));
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
                    items: (Array.isArray(json.items) ? json.items : []).filter(i => i && i.title && safeUrl(i.url)),
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
