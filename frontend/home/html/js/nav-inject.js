(function () {
  var T = {
    en: { map: 'Map', services: 'Services', data: 'Data',     stac: 'STAC', chatbot: 'AI Assistant', reportBug: 'Report a bug' },
    fr: { map: 'Carte', services: 'Services', data: 'Données', stac: 'STAC', chatbot: 'Assistant IA', reportBug: 'Signaler un bug' }
  };

  function inject() {
    if (document.getElementById('sdss-nav-host')) return;

    var lang = localStorage.getItem('sdss-lang') || 'fr';

    var host = document.createElement('div');
    host.id = 'sdss-nav-host';

    // All layout + visual styles inline with !important.
    // Shadow DOM :host styles lose to host-page author styles,
    // but inline !important is the absolute top of the cascade.
    var s = host.style;
    s.setProperty('all', 'initial', 'important');
    s.setProperty('display', 'flex', 'important');
    s.setProperty('align-items', 'center', 'important');
    s.setProperty('justify-content', 'space-between', 'important');
    s.setProperty('position', 'fixed', 'important');
    s.setProperty('top', '0', 'important');
    s.setProperty('left', '0', 'important');
    s.setProperty('right', '0', 'important');
    s.setProperty('width', '100%', 'important');
    s.setProperty('height', '42px', 'important');
    s.setProperty('box-sizing', 'border-box', 'important');
    s.setProperty('padding', '0 1.5rem', 'important');
    s.setProperty('margin', '0', 'important');
    s.setProperty('background', '#13151f', 'important');
    s.setProperty('border-bottom', '1px solid #2a2e45', 'important');
    s.setProperty('font-family', 'system-ui, sans-serif', 'important');
    s.setProperty('z-index', '2147483647', 'important');

    var shadow = host.attachShadow({ mode: 'open' });

    var path = window.location.pathname;
    var links = [
      { href: '/',         key: 'map',      nav: 'map'      },
      { href: '/services', key: 'services',  nav: 'services' },
      { href: '/data',     key: 'data',      nav: 'data'     },
      { href: '/stac/',    key: 'stac',      nav: 'stac'     },
      { href: '/chatbot/', key: 'chatbot',   nav: 'chatbot'  },
      { href: '/report-bug', key: 'reportBug', nav: 'report-bug' }
    ];

    function renderNav(l) {
      var tr = T[l] || T.fr;
      var linksHtml = links.map(function (link) {
        var isActive =
          (link.nav === 'map'      && (path === '/' || path === '/map.html')) ||
          (link.nav === 'services' && (path === '/services' || path === '/index.html')) ||
          (link.nav === 'data'     && (path === '/data' || path === '/data.html')) ||
          (link.nav === 'stac'     && path.startsWith('/stac/')) ||
          (link.nav === 'chatbot'  && path.startsWith('/chatbot/')) ||
          (link.nav === 'report-bug' && (path === '/report-bug' || path === '/report-bug.html'));
        return '<a href="' + link.href + '"' + (isActive ? ' class="active"' : '') + '>' + tr[link.key] + '</a>';
      }).join('');

      shadow.innerHTML =
        '<style>' +
        'a.brand{font-size:.95rem;font-weight:700;color:#e8eaf0;text-decoration:none;letter-spacing:-.02em;white-space:nowrap;}' +
        'a.brand span{color:#3ecf8e;}' +
        '.links{display:flex;gap:.25rem;}' +
        '.links a{padding:.3rem .75rem;border-radius:5px;font-size:.82rem;' +
        'font-weight:500;color:#8b92a8;text-decoration:none;transition:background .15s,color .15s;white-space:nowrap;}' +
        '.links a:hover{background:#22263a;color:#e8eaf0;}' +
        '.links a.active{background:#1e2438;color:#3ecf8e;}' +
        'button.lang{all:unset;margin-left:.5rem;padding:.2rem .55rem;border-radius:5px;' +
        'font-size:.72rem;font-weight:600;letter-spacing:.06em;color:#8b92a8;' +
        'border:1px solid #2a2e45;cursor:pointer;transition:background .15s,color .15s;}' +
        'button.lang:hover{background:#22263a;color:#e8eaf0;}' +
        '</style>' +
        '<a class="brand" href="/">Agri<span>-SDSS</span></a>' +
        '<div class="links">' + linksHtml + '</div>' +
        '<button class="lang" id="navLangToggle" aria-label="Switch language">' + (l === 'fr' ? 'EN' : 'FR') + '</button>';

      shadow.getElementById('navLangToggle').addEventListener('click', function () {
        lang = lang === 'fr' ? 'en' : 'fr';
        localStorage.setItem('sdss-lang', lang);
        // STAC browser caches the catalog on first load; reload so preprocessSTAC
        // re-runs with the new language and updates the title and description.
        if (window.location.pathname.startsWith('/stac/')) {
          window.location.reload();
        } else {
          renderNav(lang);
          // Notify scripts in the same document (e.g. chatbot-bridge.js) of the change.
          window.dispatchEvent(new CustomEvent('sdss-lang-change', { detail: { lang: lang } }));
        }
      });
    }

    renderNav(lang);
    document.body.insertBefore(host, document.body.firstChild);
    document.body.style.paddingTop = '42px';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
}());
