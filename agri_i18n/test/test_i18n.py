"""Unit tests for the shared agri_i18n gettext helpers.

Covers Accept-Language negotiation, context-local locale binding, catalog
lookup and the concurrency isolation that a process-global ``_`` would break.
"""

import asyncio
import gettext as _gettext

import pytest

import agri_i18n
from agri_i18n import (
    DEFAULT,
    get_locale,
    negotiate,
    ngettext,
    normalize,
    reset_locale,
    set_locale,
    use_locale,
)

# --- Accept-Language negotiation ---


@pytest.mark.unit
@pytest.mark.parametrize(
    "header,expected",
    [
        ("", DEFAULT),
        ("fr-CA,fr;q=0.9", "fr"),
        ("en-US,en;q=0.9", "en"),
        ("fr", "fr"),
        ("EN", "en"),
        ("fr_CA", "fr"),
        ("en;q=0.3,fr;q=0.9", "fr"),
        ("de,en;q=0.5", "en"),
        ("de", DEFAULT),
        ("*", DEFAULT),
        ("en;q=0", DEFAULT),
        ("  ,  ,fr  ", "fr"),
        (";;;q=abc", DEFAULT),
        ("en;q=notanumber", DEFAULT),
    ],
)
def test_negotiate_header(header, expected):
    """Header parsing honours quality ordering and never raises."""
    assert negotiate(header) == expected


@pytest.mark.unit
def test_negotiate_no_header_returns_default():
    """A missing header yields the platform default."""
    assert negotiate(None) == DEFAULT


@pytest.mark.unit
def test_explicit_overrides_header():
    """An explicit lang parameter wins over the header."""
    assert negotiate("en-US,en;q=0.9", explicit="fr") == "fr"


@pytest.mark.unit
def test_unsupported_explicit_falls_back_to_header():
    """An unsupported override is ignored rather than forcing the default."""
    assert negotiate("en-US,en;q=0.9", explicit="de") == "en"


@pytest.mark.unit
@pytest.mark.parametrize(
    "tag,expected",
    [
        ("fr-CA", "fr"),
        ("FR", "fr"),
        ("fr_CA", "fr"),
        ("en-US", "en"),
        ("de", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize(tag, expected):
    """Tags reduce to their primary subtag when supported."""
    assert normalize(tag) == expected


# --- Context-local binding ---


@pytest.mark.unit
def test_set_and_get_locale():
    """set_locale binds the context and reset_locale restores it."""
    token = set_locale("en")
    try:
        assert get_locale() == "en"
    finally:
        reset_locale(token)
    assert get_locale() == DEFAULT


@pytest.mark.unit
@pytest.mark.parametrize("code", [None, "de", ""])
def test_set_locale_rejects_unsupported(code):
    """Unsupported or missing codes bind the default."""
    token = set_locale(code)
    try:
        assert get_locale() == DEFAULT
    finally:
        reset_locale(token)


@pytest.mark.unit
def test_use_locale_restores_previous():
    """The context manager restores the enclosing locale, even on error."""
    with use_locale("en"):
        assert get_locale() == "en"
    assert get_locale() == DEFAULT

    with pytest.raises(RuntimeError):
        with use_locale("en"):
            raise RuntimeError("boom")
    assert get_locale() == DEFAULT


@pytest.mark.unit
def test_concurrent_tasks_do_not_leak_locale():
    """Interleaved asyncio tasks keep independent locales.

    This is the failure mode a process-global ``_`` would introduce.
    """

    async def worker(code: str, delay: float) -> str:
        set_locale(code)
        await asyncio.sleep(delay)
        return get_locale()

    async def main() -> list:
        return await asyncio.gather(worker("en", 0.02), worker("fr", 0.0))

    assert asyncio.run(main()) == ["en", "fr"]
    assert get_locale() == DEFAULT


# --- Catalog lookup ---


class _StubCatalog(_gettext.NullTranslations):
    """Minimal catalog standing in for a compiled .mo."""

    def gettext(self, message):
        return {"Invalid geometry": "Géométrie invalide"}.get(message, message)

    def ngettext(self, singular, plural, n):
        if n == 1:
            return "1 champ"
        return f"{n} champs"


@pytest.fixture
def stub_fr_catalog():
    """Install a stub French catalog and restore the real cache afterwards."""
    agri_i18n.clear_cache()
    agri_i18n._catalogs["fr"] = _StubCatalog()
    yield
    agri_i18n.clear_cache()


@pytest.mark.unit
def test_translates_into_bound_locale(stub_fr_catalog):
    """A bound locale with a catalog entry returns the translation."""
    with use_locale("fr"):
        assert agri_i18n._("Invalid geometry") == "Géométrie invalide"


@pytest.mark.unit
def test_english_falls_through_to_msgid(stub_fr_catalog):
    """English ships no catalog, so the msgid is returned verbatim."""
    with use_locale("en"):
        assert agri_i18n._("Invalid geometry") == "Invalid geometry"


@pytest.mark.unit
def test_missing_entry_falls_through_to_msgid(stub_fr_catalog):
    """An untranslated msgid is returned as-is rather than raising."""
    with use_locale("fr"):
        assert agri_i18n._("Not in the catalog") == "Not in the catalog"


@pytest.mark.unit
def test_ngettext_uses_locale_plural_form(stub_fr_catalog):
    """Plural lookups route through the bound locale's catalog."""
    with use_locale("fr"):
        assert ngettext("{n} field", "{n} fields", 1) == "1 champ"
        assert ngettext("{n} field", "{n} fields", 3) == "3 champs"


@pytest.mark.unit
def test_real_mo_roundtrip(tmp_path, monkeypatch):
    """A compiled .mo on disk is discovered and used.

    Guards the LOCALE_DIR/domain wiring that the stub-based tests bypass.
    """
    mofile = pytest.importorskip("babel.messages.mofile")
    catalog_mod = pytest.importorskip("babel.messages.catalog")

    catalog = catalog_mod.Catalog(locale="fr")
    catalog.add("Invalid geometry", "Géométrie invalide")

    target = tmp_path / "fr" / "LC_MESSAGES"
    target.mkdir(parents=True)
    with open(target / "messages.mo", "wb") as handle:
        mofile.write_mo(handle, catalog)

    monkeypatch.setattr(agri_i18n, "LOCALE_DIR", tmp_path)
    agri_i18n.clear_cache()
    try:
        with use_locale("fr"):
            assert agri_i18n._("Invalid geometry") == "Géométrie invalide"
        with use_locale("en"):
            assert agri_i18n._("Invalid geometry") == "Invalid geometry"
    finally:
        agri_i18n.clear_cache()


@pytest.mark.unit
def test_shipped_catalog_is_loadable():
    """An msgid absent from the catalog falls through rather than raising."""
    agri_i18n.clear_cache()
    try:
        with use_locale("fr"):
            assert agri_i18n._("untranslated probe") == "untranslated probe"
    finally:
        agri_i18n.clear_cache()


# --- Shipped catalog ---

# Representative entries from each in-scope service. Asserting real French here
# proves the .mo is compiled into the image, not just that lookup works.
_SHIPPED = [
    ("'geometry' field is required", "Le champ « geometry » est requis"),
    ("Internal database error", "Erreur interne de la base de données"),
    ("Internal server error", "Erreur interne du serveur"),
    ("GeoJSON geometry is invalid or empty",
     "La géométrie GeoJSON est invalide ou vide"),
    ("I was unable to complete the spatial analysis.",
     "Je n’ai pas pu compléter l’analyse spatiale."),
]


@pytest.mark.unit
@pytest.mark.parametrize("msgid,expected", _SHIPPED)
def test_shipped_catalog_translates_french(msgid, expected):
    """The compiled catalog resolves real messages into French."""
    agri_i18n.clear_cache()
    try:
        with use_locale("fr"):
            assert agri_i18n._(msgid) == expected
    finally:
        agri_i18n.clear_cache()


@pytest.mark.unit
@pytest.mark.parametrize("msgid,_expected", _SHIPPED)
def test_shipped_catalog_english_is_msgid(msgid, _expected):
    """English ships no catalog, so msgids pass through untouched."""
    agri_i18n.clear_cache()
    try:
        with use_locale("en"):
            assert agri_i18n._(msgid) == msgid
    finally:
        agri_i18n.clear_cache()


@pytest.mark.unit
def test_shipped_catalog_placeholders_survive_translation():
    """Named placeholders are preserved so .format() still binds them."""
    agri_i18n.clear_cache()
    try:
        with use_locale("fr"):
            rendered = agri_i18n._("Invalid geometry: {error}").format(error="bad wkt")
        assert rendered == "Géométrie invalide : bad wkt"
    finally:
        agri_i18n.clear_cache()
