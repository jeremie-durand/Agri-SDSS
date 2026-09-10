/**
 * Injected into the chatbot iframe by the home nginx sub_filter.
 * Listens for AGRI_SDSS_CONTEXT postMessages from the parent map page,
 * shows a sticky context banner, fetches real data from local Agri-SDSS APIs,
 * and injects a data-rich prompt into the chat input.
 */
(function () {
  'use strict';

  var ctx = null;

  /* ── Prompt text (FR/EN) ────────────────────────────────────────────────────
     This script runs inside the chatbot page, where map.html's window.T does not
     exist, so it carries its own dictionary and reads `sdss-lang` directly.
     The injected text is what the user sees in the composer and sends, so it is
     both the visible message and the LLM prompt — they cannot differ here. */
  var _P = {
    en: {
      attrs:        'Recorded attributes:',
      stacItem:     'Selected remote sensing item from the platform catalog:',
      parcelIntro:  'I am looking at an agricultural parcel from the Agri-SDSS platform database. Here is its recorded information:',
      parcelId:     'Parcel ID: ',
      dataset:      'Dataset: ',
      bdppadCtx:    'Dataset context: BDPPAD (Base de données sur les parcelles et propriétés agricoles du Québec) is the Quebec provincial registry of agricultural parcels. The "typpar" field is the official parcel type code; its meaning is given in the "description" field. The "suphec" field is the parcel area in hectares.',
      featureIntro: 'I am looking at a geographic feature from the Agri-SDSS platform. Here is its recorded information:',
      featureId:    'Feature ID: ',
      stacAvail:    'Remote sensing datasets available for cross-referencing on this platform:',
      askParcel:    'Please provide an agronomic analysis of this parcel based on the information above. What does the parcel type, area, and classification suggest? What kind of agricultural use or soil conditions might be expected for this type of parcel?',
      askFeature:   'Please analyze this geographic feature based on the information above. What does the data suggest about this location in the context of Quebec agriculture or land use?',
      fallbackA:    'I am looking at agricultural parcel ID ',
      fallbackB:    ' from dataset ',
      fallbackC:    ' Please provide an agronomic analysis of what you know about this kind of parcel.'
    },
    // NOTE: attrs / parcelId / featureId stay in English on purpose.
    // The upstream router agent short-circuits to `contextual` via hardcoded
    // English regexes (router_agent.py `_STRUCTURED_FEATURE_PATTERNS`:
    // /(parcel|feature|object)\s+id\s*:/ and /attributes\s*:/). Translating
    // them drops the query into the probabilistic LLM classifier, which is the
    // misrouting these overrides exist to avoid.
    fr: {
      attrs:        'Recorded attributes:',
      stacItem:     'Élément de télédétection sélectionné dans le catalogue de la plateforme :',
      parcelIntro:  'Je consulte une parcelle agricole de la base de données de la plateforme Agri-SDSS. Voici ses informations enregistrées :',
      parcelId:     'Parcel ID: ',
      dataset:      'Jeu de données : ',
      bdppadCtx:    'Contexte du jeu de données : BDPPAD (Base de données sur les parcelles et propriétés agricoles du Québec) est le registre provincial québécois des parcelles agricoles. Le champ « typpar » est le code officiel de type de parcelle ; sa signification est donnée dans le champ « description ». Le champ « suphec » correspond à la superficie de la parcelle en hectares.',
      featureIntro: 'Je consulte une entité géographique de la plateforme Agri-SDSS. Voici ses informations enregistrées :',
      featureId:    'Feature ID: ',
      stacAvail:    'Jeux de données de télédétection disponibles pour recoupement sur cette plateforme :',
      askParcel:    'Veuillez fournir une analyse agronomique de cette parcelle à partir des informations ci-dessus. Que suggèrent le type de parcelle, la superficie et la classification ? Quel usage agricole ou quelles conditions de sol peut-on attendre pour ce type de parcelle ?',
      askFeature:   'Veuillez analyser cette entité géographique à partir des informations ci-dessus. Que suggèrent ces données sur ce lieu dans le contexte de l’agriculture ou de l’occupation du sol au Québec ?',
      fallbackA:    'Je consulte la parcelle agricole ID ',
      fallbackB:    ' du jeu de données ',
      fallbackC:    ' Veuillez fournir une analyse agronomique de ce que vous savez sur ce type de parcelle.'
    }
  };

  function _p(key) {
    var lang = localStorage.getItem('sdss-lang') || 'fr';
    return (_P[lang] || _P.fr)[key];
  }

  /* ── Banner DOM ─────────────────────────────────────────────────────────── */
  var banner = document.createElement('div');
  banner.id = 'sdss-map-context';
  Object.assign(banner.style, {
    display:        'none',
    position:       'sticky',
    top:            '0',
    zIndex:         '9999',
    background:     '#1a1d2b',
    borderBottom:   '1px solid #2a2e45',
    padding:        '6px 10px',
    fontFamily:     'system-ui, sans-serif',
    fontSize:       '12px',
    color:          '#8b92a8',
    alignItems:     'center',
    gap:            '8px',
    flexWrap:       'nowrap',
    boxSizing:      'border-box',
    width:          '100%',
  });

  var label = document.createElement('span');
  Object.assign(label.style, {
    flex:           '1',
    overflow:       'hidden',
    textOverflow:   'ellipsis',
    whiteSpace:     'nowrap',
  });

  var analyseBtn = document.createElement('button');
  analyseBtn.textContent = 'Analyse →';
  Object.assign(analyseBtn.style, {
    background:   '#3ecf8e',
    color:        '#0f1117',
    border:       'none',
    borderRadius: '4px',
    padding:      '3px 8px',
    fontSize:     '11px',
    fontWeight:   '600',
    cursor:       'pointer',
    whiteSpace:   'nowrap',
    flexShrink:   '0',
  });

  var closeBtn = document.createElement('button');
  closeBtn.textContent = '×';
  Object.assign(closeBtn.style, {
    background: 'none',
    border:     'none',
    color:      '#8b92a8',
    cursor:     'pointer',
    fontSize:   '16px',
    lineHeight: '1',
    padding:    '0 2px',
    flexShrink: '0',
  });

  banner.appendChild(label);
  banner.appendChild(analyseBtn);
  banner.appendChild(closeBtn);

  /* ── Helpers ────────────────────────────────────────────────────────────── */
  function mountBanner() {
    if (!document.getElementById('sdss-map-context') && document.body) {
      document.body.insertBefore(banner, document.body.firstChild);
    }
  }

  function showContext(data) {
    ctx = data;
    var id  = data.featureId  || '';
    var col = data.collection || '';
    label.textContent = '📍 ' + (id ? id + ' — ' : '') + col;
    banner.style.display = 'flex';
    mountBanner();
  }

  function hideContext() {
    banner.style.display = 'none';
    ctx = null;
  }

  /* ── Fetch helpers ──────────────────────────────────────────────────────── */
  var _ACCEPT_LANGUAGE = { fr: 'fr-CA,fr;q=0.9', en: 'en-US,en;q=0.9' };

  function _acceptLanguage() {
    var lang = localStorage.getItem('sdss-lang') || 'fr';
    return _ACCEPT_LANGUAGE[lang] || _ACCEPT_LANGUAGE.fr;
  }

  async function fetchJson(url) {
    try {
      var r = await fetch(url, {
        headers: { Accept: 'application/json', 'Accept-Language': _acceptLanguage() }
      });
      return r.ok ? r.json() : null;
    } catch (_) {
      return null;
    }
  }

  function buildPropsSection(props) {
    var keys = Object.keys(props).filter(function (k) {
      var v = props[k];
      return v !== null && v !== undefined && v !== '';
    });
    if (!keys.length) return '';
    var lines = [_p('attrs')];
    keys.forEach(function (k) { lines.push('  ' + k + ': ' + props[k]); });
    return lines.join('\n');
  }

  /**
   * Fetches real parcel data from local Agri-SDSS APIs, then injects an
   * analysis-framed prompt into the chatbot textarea.
   * The prompt avoids location/satellite keywords so the router agent
   * routes to answer_contextual_question (LLM analysis mode).
   */
  function buildStacItemSection(item) {
    if (!item || item.type !== 'Feature') return '';
    var lines = [];
    var props = item.properties || {};
    lines.push(_p('stacItem'));
    lines.push('  id: ' + (item.id || 'unknown'));
    lines.push('  collection: ' + (item.collection || (props.collection || 'unknown')));
    if (item.bbox) {
      lines.push('  bbox: ' + item.bbox.join(', '));
    }
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v !== null && v !== undefined && v !== '') {
        lines.push('  ' + k + ': ' + v);
      }
    });
    return lines.join('\n');
  }

  function injectPrompt() {
    if (!ctx) return;

    var id       = ctx.featureId  || '';
    var col      = ctx.collection || '';
    var props    = ctx.properties || {};
    var center   = ctx.center || null;
    var stacItem = ctx.stacItem   || null;

    analyseBtn.textContent = 'Loading…';
    analyseBtn.disabled = true;

    var vectorUrl = id && col
      ? '/vector-api/parquet/collections/' + encodeURIComponent(col) + '/items/' + encodeURIComponent(id)
      : null;

    Promise.all([
      fetchJson('/stac-api/collections'),
      vectorUrl ? fetchJson(vectorUrl) : Promise.resolve(null)
    ]).then(function (results) {
      var stacResult  = results[0];
      var featureData = results[1];

      /* Merge properties: postMessage snapshot + freshly-fetched full feature */
      var mergedProps = Object.assign({}, props);
      if (featureData && featureData.properties) {
        Object.assign(mergedProps, featureData.properties);
      }

      var isBdppad = col.toLowerCase().indexOf('bdppad') === 0;

      var lines = [];
      /* Coordinates intentionally omitted — the router agent misroutes lat/lon
         strings to navigate_to. Feature ID + dataset are sufficient for analysis. */
      if (isBdppad) {
        lines.push(_p('parcelIntro'));
        lines.push('');
        if (id)  lines.push(_p('parcelId') + id);
        if (col) lines.push(_p('dataset') + col);
        lines.push('');
        lines.push(_p('bdppadCtx'));
      } else {
        lines.push(_p('featureIntro'));
        lines.push('');
        if (id)  lines.push(_p('featureId') + id);
        if (col) lines.push(_p('dataset') + col);
      }

      var propsSection = buildPropsSection(mergedProps);
      if (propsSection) {
        lines.push('');
        lines.push(propsSection);
      }

      /* List real remote sensing collections only — exclude demo/test collections
         and avoid satellite brand names that trigger the router's STAC_SEARCH routing. */
      var EXCLUDED_COLLECTIONS = ['demo_collection'];
      if (stacResult && stacResult.collections && stacResult.collections.length) {
        var realCollections = stacResult.collections.filter(function (c) {
          return EXCLUDED_COLLECTIONS.indexOf(c.id) === -1;
        });
        if (realCollections.length) {
          lines.push('');
          lines.push(_p('stacAvail'));
          realCollections.forEach(function (c) {
            lines.push('  - ' + c.id);
          });
        }
      }

      var stacSection = buildStacItemSection(stacItem);
      if (stacSection) {
        lines.push('');
        lines.push(stacSection);
      }

      lines.push('');
      if (isBdppad) {
        lines.push(_p('askParcel'));
      } else {
        lines.push(_p('askFeature'));
      }

      injectText(lines.join('\n'));

    }).catch(function () {
      /* Fallback if API calls fail */
      var text = _p('fallbackA') + id
        + _p('fallbackB') + col + '.'
        + _p('fallbackC');
      injectText(text);
    }).finally(function () {
      analyseBtn.textContent = 'Analyse →';
      analyseBtn.disabled = false;
    });
  }

  /* Inject text into the React-controlled chatbot textarea and submit focus. */
  function injectText(text) {
    var textarea = document.querySelector('textarea');
    if (!textarea) return;
    var proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
    if (proto && proto.set) {
      proto.set.call(textarea, text);
    } else {
      textarea.value = text;
    }
    textarea.dispatchEvent(new Event('input',  { bubbles: true }));
    textarea.dispatchEvent(new Event('change', { bubbles: true }));
    textarea.focus();
  }

  /* ── Fetch interceptor: forward map data from backend responses to parent ── */
  var MAP_ENDPOINTS = /\/(chat|unified-chat|enhanced-chat|query|intelligent-route|sign-mosaic-url)/;

  function isGeoBbox(arr) {
    return arr.length === 4
      && arr.every(function (v) { return typeof v === 'number'; })
      && arr[0] >= -180 && arr[2] <= 180
      && arr[1] >= -90  && arr[3] <= 90
      && arr[0] < arr[2] && arr[1] < arr[3];
  }

  function findBbox(obj, depth) {
    if (!obj || depth > 6) return null;
    if (Array.isArray(obj)) {
      if (isGeoBbox(obj)) return obj;
      for (var i = 0; i < obj.length; i++) {
        var r = findBbox(obj[i], depth + 1);
        if (r) return r;
      }
    } else if (typeof obj === 'object') {
      /* Check 'bbox' key first */
      if (Array.isArray(obj.bbox) && isGeoBbox(obj.bbox)) return obj.bbox;
      var keys = Object.keys(obj);
      for (var j = 0; j < keys.length; j++) {
        if (keys[j] === 'bbox') continue;
        var r2 = findBbox(obj[keys[j]], depth + 1);
        if (r2) return r2;
      }
    }
    return null;
  }

  function sendTileUrl(url) {
    url = url.replace(/^\/api\/raster\//, '/raster-api/');
    window.parent.postMessage({ type: 'AGRI_SDSS_TILES', url: url }, '*');
  }

  function forwardTileUrl(data) {
    if (!data || typeof data.signed_url !== 'string') return;
    var url = data.signed_url;
    if (url.indexOf('{z}') !== -1) {
      /* Direct XYZ tile template */
      sendTileUrl(url);
    } else if (/tilejson\.json/.test(url)) {
      /* TiTiler tilejson endpoint — fetch it to extract the XYZ tile template */
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (tj) {
          if (tj.tiles && tj.tiles.length > 0) sendTileUrl(tj.tiles[0]);
        })
        .catch(function () {});
    }
  }

  function forwardMapData(data) {
    if (!data || typeof data !== 'object') return;

    // navigate_to: prefer lat/lon (unambiguous) over bbox (coordinate order can be ambiguous)
    if (data.action === 'navigate_to' && data.navigate_to) {
      var nav = data.navigate_to;
      if (typeof nav.latitude === 'number' && typeof nav.longitude === 'number') {
        window.parent.postMessage({
          type: 'AGRI_SDSS_ZOOM',
          lat: nav.latitude,
          lon: nav.longitude,
          zoom: nav.zoom || 10
        }, '*');
      } else if (Array.isArray(nav.bbox) && isGeoBbox(nav.bbox)) {
        window.parent.postMessage({ type: 'AGRI_SDSS_ZOOM', bbox: nav.bbox }, '*');
      }
      return;
    }

    // Any other response: scan for the first valid geo bbox anywhere in the payload
    var bbox = findBbox(data, 0);
    if (bbox) {
      var bboxW = Math.abs(bbox[2] - bbox[0]);
      var bboxH = Math.abs(bbox[3] - bbox[1]);
      if (bboxW > 5 || bboxH > 5) {
        /* Bbox too large (e.g. MODIS tile covering all of eastern Canada) —
           zoom to centroid at a moderate level instead of fitting the full extent */
        window.parent.postMessage({
          type: 'AGRI_SDSS_ZOOM',
          lat: (bbox[1] + bbox[3]) / 2,
          lon: (bbox[0] + bbox[2]) / 2,
          zoom: 8
        }, '*');
      } else {
        window.parent.postMessage({ type: 'AGRI_SDSS_ZOOM', bbox: bbox }, '*');
      }
    }
  }

  function dispatchResponse(url, data) {
    if (/sign-mosaic-url/.test(url)) {
      forwardTileUrl(data);
    } else {
      forwardMapData(data);
    }
  }

  (function patchFetch() {
    var _fetch = window.fetch;
    window.fetch = async function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var response = await _fetch.call(this, input, init);
      if (MAP_ENDPOINTS.test(url)) {
        response.clone().json().then(function (data) { dispatchResponse(url, data); }).catch(function () {});
      }
      return response;
    };
  }());

  /* Axios uses XMLHttpRequest, not fetch — patch XHR to intercept map responses. */
  (function patchXhr() {
    var _open = XMLHttpRequest.prototype.open;
    var _send = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url) {
      this._mosUrl = url || '';
      return _open.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function () {
      if (MAP_ENDPOINTS.test(this._mosUrl)) {
        var mosUrl = this._mosUrl;
        this.addEventListener('load', function () {
          try {
            dispatchResponse(mosUrl, JSON.parse(this.responseText));
          } catch (_) {}
        });
      }
      return _send.apply(this, arguments);
    };
  }());

  /* ── Event listeners ────────────────────────────────────────────────────── */
  analyseBtn.addEventListener('click', injectPrompt);
  closeBtn.addEventListener('click', hideContext);

  window.addEventListener('message', function (e) {
    if (!e.data || e.data.type !== 'AGRI_SDSS_CONTEXT') return;
    showContext(e.data);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountBanner);
  } else {
    mountBanner();
  }

  /* ── Agri-SDSS greeting override ─────────────────────────────────────────── */
  /* Upstream owns the greeting and (since the chat.welcome key landed) translates
     it. We override only the wording, to carry Agri-SDSS branding and the Québec
     framing. Matching covers upstream's greeting in both languages and our own,
     so one pass finds the message whatever it currently says and writes the text
     for the active language — correct in both directions, and on upstream builds
     that still fix the greeting in English at mount time. */
  (function () {
    var MSGS = {
      en: 'Welcome to the Agri-SDSS AI Assistant! I\'m here to help you find geospatial data with location and date details. Whether you\'re analysing temporal trends or exploring spatial insights across Québec, I\'ve got you covered. Just tell me what you\'re working on, and we\'ll get started!',
      fr: 'Bienvenue sur l\'Assistant IA Agri-SDSS ! Je suis ici pour vous aider à trouver des données géospatiales avec des détails de localisation et de date. Que vous analysiez des tendances temporelles ou exploriez des aperçus spatiaux sur le Québec, je suis là pour vous. Dites-moi sur quoi vous travaillez, et commençons !'
    };

    // Opening words of every greeting we may meet in the DOM — upstream's, and ours.
    var SNIPPETS = [
      'Welcome to OpenGeo AI Assistant',
      'Bienvenue sur OpenGeo AI Assistant',
      'Welcome to the Agri-SDSS AI Assistant',
      'Bienvenue sur l\'Assistant IA Agri-SDSS'
    ];

    function isGreeting(text) {
      for (var i = 0; i < SNIPPETS.length; i++) {
        if (text.indexOf(SNIPPETS[i]) !== -1) return true;
      }
      return false;
    }

    function applyWelcome(lang) {
      var to = MSGS[lang] || MSGS.fr;

      // Text node path (plain React render)
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
      var node;
      while ((node = walker.nextNode())) {
        if (node.nodeValue && isGreeting(node.nodeValue)) {
          if (node.nodeValue !== to) node.nodeValue = to;
          return true;
        }
      }
      // innerHTML path (dangerouslySetInnerHTML)
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.children.length === 0 && el.innerHTML && isGreeting(el.innerHTML)) {
          if (el.innerHTML !== to) el.innerHTML = to;
          return true;
        }
      }
      return false;
    }

    function currentLang() {
      return localStorage.getItem('sdss-lang') || 'fr';
    }

    // Stays connected: the greeting is rendered on mount and, on upstream builds
    // that translate it reactively, re-rendered on every host language switch.
    // Loop-safe — applyWelcome writes nothing once the text already matches.
    var observer = new MutationObserver(function () {
      applyWelcome(currentLang());
    });

    function start() {
      applyWelcome(currentLang());
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    // Upstream builds that fix the greeting in English at mount never re-render
    // it, so the observer alone would leave it stale — apply the switch directly.
    window.addEventListener('sdss-lang-change', function (e) {
      applyWelcome((e.detail && e.detail.lang) || currentLang());
    });

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', start);
    } else {
      start();
    }
  }());
}());
