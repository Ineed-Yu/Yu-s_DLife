// ページの言語（<html lang>）を、言語切替（JP/EN/FR/ZH）に合わせる。
// フォントを言語ごとに正しい字形で表示するため（中国語は簡体字の字形、日本語は日本の字形）。
// ブログは言語ごとに URL が分かれていて、各ページの lang が最初から正しいので何もしない。
(function () {
    'use strict';
    var MAP = { ja: 'ja', en: 'en', fr: 'fr', zh: 'zh-CN' };
    if (/^\/(?:(?:en|fr|zh)\/)?blog\//.test(location.pathname)) return;
    function set(lang) {
        if (MAP[lang]) document.documentElement.lang = MAP[lang];
    }
    try {
        set(localStorage.getItem('selectedLanguage'));
    } catch (e) {}
    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.lang-btn') : null;
        if (btn) set(btn.getAttribute('data-lang') || String(btn.id || '').replace(/^btn-/, ''));
    }, true);
})();
