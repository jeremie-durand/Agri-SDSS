// welcome-modal.js — first-visit welcome popup, shown once per platform version.
// Self-contained (injects its own styles + DOM) so it looks consistent across
// map.html, index.html, and data.html regardless of which stylesheet each
// page loads. Shown again automatically whenever PLATFORM_VERSION changes.
(function () {
    var PLATFORM_VERSION = '1.0.0';
    var SEEN_KEY = 'sdss-welcome-version-seen';
    var ISSUES_URL = 'https://github.com/jeremie-durand/Agri-SDSS/issues';

    var T = {
        en: {
            title: 'Welcome to Agri-SDSS',
            version: 'Version',
            body: 'This platform is still in active development — you may run into bugs or unfinished features.',
            link: 'Report an issue on GitHub',
            dismiss: 'Got it',
        },
        fr: {
            title: 'Bienvenue sur Agri-SDSS',
            version: 'Version',
            body: 'Cette plateforme est encore en développement actif — vous pourriez rencontrer des bugs ou des fonctionnalités incomplètes.',
            link: 'Signaler un problème sur GitHub',
            dismiss: 'Compris',
        },
    };

    function getLang() {
        var lang = localStorage.getItem('sdss-lang') || 'fr';
        return T[lang] ? lang : 'fr';
    }

    function injectStyles() {
        if (document.getElementById('sdss-welcome-modal-style')) return;
        var style = document.createElement('style');
        style.id = 'sdss-welcome-modal-style';
        style.textContent =
            '.sdss-welcome-modal { position: fixed; inset: 0; z-index: 9999; display: flex; align-items: center; justify-content: center; }' +
            '.sdss-welcome-modal__backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.55); }' +
            '.sdss-welcome-modal__dialog { position: relative; z-index: 1; background: var(--surface, #1a1d27); border: 1px solid var(--border, #2a2e45); border-radius: 12px; width: min(440px, 92vw); padding: 1.5rem; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4); }' +
            '.sdss-welcome-modal__header { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.85rem; }' +
            '.sdss-welcome-modal__header h2 { font-size: 1.1rem; font-weight: 700; margin: 0; color: var(--text-primary, #e8eaf0); }' +
            '.sdss-welcome-modal__badge { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.04em; padding: 0.15rem 0.5rem; border-radius: 999px; background: rgba(62, 207, 142, 0.15); color: var(--accent, #3ecf8e); border: 1px solid var(--accent, #3ecf8e); white-space: nowrap; }' +
            '.sdss-welcome-modal__body { font-size: 0.88rem; line-height: 1.55; color: var(--text-secondary, #8b92a8); margin: 0 0 1rem 0; }' +
            '.sdss-welcome-modal__link { display: inline-block; margin-bottom: 1.25rem; font-size: 0.85rem; color: var(--accent, #3ecf8e); text-decoration: underline; }' +
            '.sdss-welcome-modal__actions { display: flex; justify-content: flex-end; }' +
            '.sdss-welcome-modal__dismiss { font: inherit; font-weight: 600; font-size: 0.85rem; padding: 0.5rem 1.1rem; border-radius: 6px; cursor: pointer; background: var(--accent, #3ecf8e); color: #06251a; border: none; }' +
            '.sdss-welcome-modal__dismiss:hover { filter: brightness(1.08); }';
        document.head.appendChild(style);
    }

    function showWelcomeModal() {
        var t = T[getLang()];

        injectStyles();

        var modal = document.createElement('div');
        modal.className = 'sdss-welcome-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.innerHTML =
            '<div class="sdss-welcome-modal__backdrop"></div>' +
            '<div class="sdss-welcome-modal__dialog">' +
            '  <div class="sdss-welcome-modal__header">' +
            '    <h2>' + t.title + '</h2>' +
            '    <span class="sdss-welcome-modal__badge">' + t.version + ' ' + PLATFORM_VERSION + '</span>' +
            '  </div>' +
            '  <p class="sdss-welcome-modal__body">' + t.body + '</p>' +
            '  <a class="sdss-welcome-modal__link" href="' + ISSUES_URL + '" target="_blank" rel="noopener">' + t.link + '</a>' +
            '  <div class="sdss-welcome-modal__actions">' +
            '    <button type="button" class="sdss-welcome-modal__dismiss">' + t.dismiss + '</button>' +
            '  </div>' +
            '</div>';

        document.body.appendChild(modal);

        var onKeydown = function (e) {
            if (e.key === 'Escape') close();
        };

        function close() {
            localStorage.setItem(SEEN_KEY, PLATFORM_VERSION);
            document.removeEventListener('keydown', onKeydown);
            modal.remove();
        }

        modal.querySelector('.sdss-welcome-modal__backdrop').addEventListener('click', close);
        modal.querySelector('.sdss-welcome-modal__dismiss').addEventListener('click', close);
        document.addEventListener('keydown', onKeydown);
    }

    if (localStorage.getItem(SEEN_KEY) !== PLATFORM_VERSION) {
        showWelcomeModal();
    }
})();
