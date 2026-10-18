// ブログ（フィルム風デザイン）の表示処理。一覧と記事ページの両方で使う。
// 言語ごとに URL が分かれている：日本語 /blog/…、英語 /en/blog/…、フランス語 /fr/blog/…、中国語 /zh/blog/…
//   言語ボタンを押すと、その言語版のページ（<link rel="alternate" hreflang> に書かれた URL）へ移動する。
//   その言語版が無い記事では、日本語の本文のまま画面の文字だけ切り替え「日本語のみ」と表示する。
// 一覧のデータは /blog/posts.json、ジャンルは /blog/genres.json（どちらも tools/build_blog.py が原稿から自動で作る）。
// 一覧は ?genre=ジャンルid / ?tag=タグ で絞り込める。
// 文字はすべて textContent で入れ、HTML として解釈させない（記事データに < > などが入っても安全）。
(function () {
    'use strict';

    // ---------- 言語切替（他の準備中ページと同じ仕組み） ----------
    const SUPPORTED_LANGS = ['ja', 'en', 'fr', 'zh'];

    function normalizeLanguage(lang) {
        return SUPPORTED_LANGS.includes(lang) ? lang : 'ja';
    }

    function getSavedLanguage() {
        try {
            return normalizeLanguage(localStorage.getItem('selectedLanguage'));
        } catch (e) {
            return 'ja';
        }
    }

    function saveLanguage(lang) {
        try {
            localStorage.setItem('selectedLanguage', lang);
        } catch (e) {}
    }

    // このページの言語（<html lang="en"> など）
    const PAGE_LANG = normalizeLanguage(String(document.documentElement.lang || 'ja').slice(0, 2));
    let currentLang = PAGE_LANG;

    // 一覧ページかどうか（一覧は全言語に必ずある）
    const IS_LIST = !!document.getElementById('film-frames');
    function listUrl(lang) {
        return lang === 'ja' ? '/blog/' : `/${lang}/blog/`;
    }

    // 各言語版の URL（記事ページは <link rel="alternate" hreflang>、一覧は決まった URL）
    function alternateUrl(lang) {
        if (lang === PAGE_LANG) return location.pathname;
        if (IS_LIST) return listUrl(lang);
        const code = lang === 'zh' ? 'zh-Hans' : lang;
        const link = document.querySelector(`link[rel="alternate"][hreflang="${code}"]`);
        if (!link) return null;
        // 移動先はこのサイト内のブログの URL の形に限る（パスだけを使うので、確認用の環境でも同じように動く）
        try {
            const path = new URL(link.href, location.href).pathname;
            return /^\/(?:(?:en|fr|zh)\/)?blog\/[a-z0-9-]+\/$/.test(path) ? path : null;
        } catch (e) {
            return null;
        }
    }

    function goTo(path) {
        if (path && path !== location.pathname) location.assign(path + location.search);
    }

    // 言語ボタン：その言語版へ移動。無ければ日本語版のまま表示の言語だけ切り替える
    function chooseLanguage(lang) {
        lang = normalizeLanguage(lang);
        saveLanguage(lang);
        const target = alternateUrl(lang);
        if (target) {
            if (target === location.pathname) switchLanguage(lang);
            else goTo(target);
        } else if (PAGE_LANG === 'ja') {
            switchLanguage(lang);
        } else {
            goTo(alternateUrl('ja'));  // 日本語版へ（そこで選んだ言語の表示になる）
        }
    }

    function switchLanguage(lang) {
        currentLang = normalizeLanguage(lang);
        applyArticleLanguage(currentLang);
        document.querySelectorAll('[data-ja]').forEach(el => {
            el.textContent = el.getAttribute('data-' + currentLang) || el.getAttribute('data-ja');
        });
        document.querySelectorAll('.nav-link').forEach(link => {
            const targetUrl = link.getAttribute(`data-url-${currentLang}`);
            if (targetUrl) link.href = targetUrl;
        });
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === currentLang);
        });
        document.dispatchEvent(new CustomEvent('site:languagechange'));
    }

    // ---------- 記事ページ：その言語版が無いときの注記 ----------
    function applyArticleLanguage(lang) {
        const jaOnly = document.querySelector('.article-ja-only');
        if (jaOnly) jaOnly.hidden = !(PAGE_LANG === 'ja' && lang !== 'ja');
    }

    // ---------- 記事データ ----------
    let postsCache = null;

    let genresCache = null;
    function loadGenres() {
        if (!genresCache) {
            genresCache = fetch('/blog/genres.json')
                .then(r => r.json())
                .then(list => (Array.isArray(list) ? list : []))
                .catch(() => []);
        }
        return genresCache;
    }

    function loadPosts() {
        if (!postsCache) {
            postsCache = fetch('/blog/posts.json')
                .then(r => r.json())
                .then(list => (Array.isArray(list) ? list : [])
                    .filter(p => p && !p.Draft && p.Id)
                    .sort((a, b) => String(b.Date || '').localeCompare(String(a.Date || ''))));
        }
        return postsCache;
    }

    // その言語の項目（例: post.en.Title・post.en.Url）で上書きする。一覧はページの言語で表示する
    function localized(post) {
        return Object.assign({}, post, post[PAGE_LANG] || {});
    }

    // このページの言語で読める記事（日本語の一覧は全記事、他の言語は翻訳がある記事だけ）
    function availableHere(post) {
        return PAGE_LANG === 'ja' || !!post[PAGE_LANG];
    }

    // data.json の元画像パスから、tools/optimize_images.py が作った軽量版のパスを作る（ピンボードと同じ規則）
    function optimizedImage(path, width) {
        const m = String(path || '').match(/^(.*\/)?images\/([^/]+)\.(jpe?g|png)$/i);
        if (!m) return path;
        return `${m[1] || ''}images/opt/${m[2].replace(/^_+/, '')}-${width}.webp`;
    }

    function makeImage(path, width, alt) {
        const img = document.createElement('img');
        img.alt = alt || '';
        img.decoding = 'async';
        img.onerror = () => { img.onerror = null; img.src = path; };
        img.src = optimizedImage(path, width);
        return img;
    }

    // '26 10 14 の形（フィルムカメラの日付写し込み風）
    function dateStamp(iso) {
        const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
        return m ? `'${m[1].slice(2)} ${m[2]} ${m[3]}` : '';
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // 赤い色鉛筆の手描きの囲み
    function greaseMark() {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'grease-mark');
        svg.setAttribute('viewBox', '0 0 100 100');
        svg.setAttribute('preserveAspectRatio', 'none');
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', 'M2.5 3 C 30 0.5, 70 1.5, 98.5 1.5 C 99.6 35, 98.4 68, 98.8 97.5 C 70 99.5, 32 98.2, 1.2 98.6 C 0.4 70, 1.2 34, 1.8 5 L 11 1');
        path.setAttribute('pathLength', '1');
        svg.appendChild(path);
        return svg;
    }

    function frameNumber(n) {
        const edge = el('span', 'edge-print frame-number');
        edge.setAttribute('aria-hidden', 'true');
        edge.appendChild(el('span', '', String(n)));
        return edge;
    }

    // 記事ページの URL（/blog/… または /en/blog/… など、同じサイト内の決まった形の URL だけを使う）
    function postUrl(post) {
        const url = String(post.Url || '');
        return /^\/(?:(?:en|fr|zh)\/)?blog\/[a-z0-9-]+\/$/.test(url) ? url : `/blog/${encodeURIComponent(post.Id)}/`;
    }

    function buildFrame(post, n) {
        const p = localized(post);
        const li = document.createElement('li');
        li.appendChild(frameNumber(n));

        const frame = el('a', 'frame');
        frame.href = postUrl(p);
        if (p.Image) {
            frame.appendChild(makeImage(p.Image, 960, ''));
        } else {
            frame.classList.add('is-unexposed');  // 写真の無い記事は、何も写っていないコマ
        }

        const caption = el('div', 'frame-caption');
        caption.appendChild(el('h2', 'frame-title', p.Title || ''));
        const stamp = el('time', 'date-stamp', dateStamp(p.Date));
        if (p.Date) stamp.dateTime = p.Date;
        caption.appendChild(stamp);
        frame.appendChild(caption);

        li.appendChild(frame);
        // 色鉛筆の印はコマの外側（フィルムの縁）に描くので、コマの隣に置く
        li.appendChild(greaseMark());
        return li;
    }

    // ---------- 一覧ページ：ジャンル・タグでの絞り込み ----------
    const ALL_LABEL = { ja: 'すべて', en: 'All', fr: 'Tous', zh: '全部' };

    function currentFilter() {
        const q = new URLSearchParams(location.search);
        return { genre: q.get('genre') || '', tag: q.get('tag') || '' };
    }

    function setFilter(next) {
        const q = new URLSearchParams();
        if (next.genre) q.set('genre', next.genre);
        if (next.tag) q.set('tag', next.tag);
        const search = q.toString();
        history.pushState(null, '', location.pathname + (search ? '?' + search : ''));
        renderList();
    }

    function matches(post, f) {
        if (f.genre && !(post.Genres || []).includes(f.genre)) return false;
        if (f.tag && !(post.Tags || []).includes(f.tag)) return false;
        return true;
    }

    // タグの表示名（翻訳があればその言語で）
    function tagLabel(tag, posts) {
        for (const post of posts) {
            const i = (post.Tags || []).indexOf(tag);
            if (i >= 0) {
                const t = post[currentLang] && post[currentLang].Tags;
                return '#' + ((t && t[i]) || tag);
            }
        }
        return '#' + tag;
    }

    function chip(text, pressed, onClick, title) {
        const b = el('button', 'film-filter-chip', text);
        b.type = 'button';
        b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
        if (title) b.title = title;
        b.addEventListener('click', onClick);
        return b;
    }

    function renderFilter(genres, posts, f) {
        const nav = document.getElementById('film-filter');
        if (!nav) return;
        nav.replaceChildren();
        const used = genres.filter(g => posts.some(p => (p.Genres || []).includes(g.Id)));
        if (!posts.length || (!used.length && !f.tag)) {
            nav.hidden = true;
            return;
        }
        nav.hidden = false;
        nav.appendChild(chip(ALL_LABEL[currentLang] || ALL_LABEL.ja, !f.genre && !f.tag, () => setFilter({})));
        used.forEach(g => {
            const t = g[currentLang] || g.ja || {};
            nav.appendChild(chip(t.Label || g.Id, f.genre === g.Id,
                () => setFilter({ genre: f.genre === g.Id ? '' : g.Id, tag: f.tag }), t.Name));
        });
        if (f.tag) {
            const c = chip(tagLabel(f.tag, posts) + ' ×', true, () => setFilter({ genre: f.genre }));
            c.classList.add('is-tag');
            nav.appendChild(c);
        }
    }

    // ---------- 一覧ページ ----------
    function renderList() {
        const list = document.getElementById('film-frames');
        const empty = document.getElementById('film-empty');
        const noMatch = document.getElementById('film-nomatch');
        if (!list) return;
        Promise.all([loadPosts(), loadGenres()]).then(([all, genres]) => {
            const posts = all.filter(availableHere);
            const f = currentFilter();
            renderFilter(genres, posts, f);
            const shown = posts.filter(p => matches(p, f));
            list.querySelectorAll('li[data-post]').forEach(li => li.remove());
            shown.forEach(post => {
                // コマ番号は古い記事から 1, 2, 3 …（絞り込んでも、新しい記事が増えても番号は変わらない）
                const li = buildFrame(post, post.Number || all.length - all.indexOf(post));
                li.dataset.post = post.Id;
                list.appendChild(li);
            });
            if (empty) empty.hidden = posts.length > 0;
            if (noMatch) noMatch.hidden = !(posts.length > 0 && shown.length === 0);
        }).catch(err => {
            console.error('記事データの読み込みに失敗しました:', err);
            if (empty) empty.hidden = false;
        });
    }

    // サイト内から来たときは、前に選んだ言語の版へ移動する（検索結果などサイト外から来たときは、そのページの言語を優先）
    function fromThisSite() {
        try {
            return !!document.referrer && new URL(document.referrer).origin === location.origin;
        } catch (e) {
            return false;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => chooseLanguage(btn.dataset.lang));
        });
        const saved = getSavedLanguage();
        if (fromThisSite() && saved !== PAGE_LANG) {
            const target = alternateUrl(saved);
            if (target && target !== location.pathname) {
                location.replace(target + location.search);
                return;
            }
            // その言語版が無い：日本語版なら表示の言語だけ切り替える
            if (PAGE_LANG === 'ja') {
                switchLanguage(saved);
                renderList();
                return;
            }
        }
        saveLanguage(PAGE_LANG);
        if (PAGE_LANG !== 'ja') switchLanguage(PAGE_LANG);
        renderList();
    });
    document.addEventListener('site:languagechange', () => {
        renderList();
    });
    window.addEventListener('popstate', renderList);
})();
