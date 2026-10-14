// ブログ（フィルム風デザイン）の表示処理。一覧 /blog/ と記事ページ /blog/post.html で共通。
// 記事データは /blog/posts.json。"Draft": true の記事は表示しない。
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

    let currentLang = 'ja';

    function switchLanguage(lang) {
        currentLang = normalizeLanguage(lang);
        try {
            localStorage.setItem('selectedLanguage', currentLang);
        } catch (e) {}
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

    // ---------- 記事データ ----------
    let postsCache = null;

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

    // 言語別の項目（例: post.en.Title）があれば、その項目だけ上書きする
    function localized(post) {
        return Object.assign({}, post, post[currentLang] || {});
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

    function buildFrame(post, n, asLink) {
        const p = localized(post);
        const li = document.createElement('li');
        li.appendChild(frameNumber(n));

        const frame = el(asLink ? 'a' : 'div', 'frame');
        if (asLink) frame.href = `/blog/post.html?id=${encodeURIComponent(post.Id)}`;
        frame.appendChild(makeImage(p.Image, asLink ? 960 : 1600, ''));

        const caption = el('div', 'frame-caption');
        caption.appendChild(el(asLink ? 'h2' : 'p', 'frame-title', p.Title || ''));
        const stamp = el('time', 'date-stamp', dateStamp(p.Date));
        if (p.Date) stamp.dateTime = p.Date;
        caption.appendChild(stamp);
        frame.appendChild(caption);

        li.appendChild(frame);
        // 色鉛筆の印はコマの外側（フィルムの縁）に描くので、コマの隣に置く
        if (asLink) li.appendChild(greaseMark());
        return li;
    }

    // ---------- 一覧ページ ----------
    function renderList() {
        const list = document.getElementById('film-frames');
        const empty = document.getElementById('film-empty');
        if (!list) return;
        loadPosts().then(posts => {
            list.querySelectorAll('li[data-post]').forEach(li => li.remove());
            posts.forEach((post, i) => {
                const li = buildFrame(post, i + 1, true);
                li.dataset.post = post.Id;
                list.appendChild(li);
            });
            if (empty) empty.hidden = posts.length > 0;
        }).catch(err => {
            console.error('記事データの読み込みに失敗しました:', err);
            if (empty) empty.hidden = false;
        });
    }

    // ---------- 記事ページ ----------
    function renderPost() {
        const holder = document.getElementById('post');
        if (!holder) return;
        const id = new URLSearchParams(location.search).get('id');
        const missing = document.getElementById('post-missing');
        const strip = document.getElementById('post-strip');
        loadPosts().then(posts => {
            const index = posts.findIndex(p => p.Id === id);
            const frames = document.getElementById('film-frames');
            frames.textContent = '';
            holder.textContent = '';
            if (index < 0) {
                missing.hidden = false;
                strip.hidden = true;
                return;
            }
            missing.hidden = true;
            strip.hidden = false;
            const post = posts[index];
            const p = localized(post);
            frames.appendChild(buildFrame(post, index + 1, false));

            holder.appendChild(el('h1', 'article-title', p.Title || ''));
            const date = el('time', 'article-date', String(p.Date || '').replace(/-/g, '.'));
            if (p.Date) date.dateTime = p.Date;
            holder.appendChild(date);
            const body = el('div', 'article-body');
            (Array.isArray(p.Body) ? p.Body : [p.Body || '']).forEach(text => body.appendChild(el('p', '', text)));
            holder.appendChild(body);
            document.title = `${p.Title || 'Blog'} | Yu's DLife`;
        }).catch(err => {
            console.error('記事データの読み込みに失敗しました:', err);
            missing.hidden = false;
            strip.hidden = true;
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => switchLanguage(btn.dataset.lang));
        });
        currentLang = getSavedLanguage();
        if (currentLang !== 'ja') switchLanguage(currentLang);
        renderList();
        renderPost();
    });
    document.addEventListener('site:languagechange', () => {
        renderList();
        renderPost();
    });
})();
