import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const mapHtmlDir = path.resolve(here, "../html");
const fixtureDir = path.resolve(here, "fixtures/missing-i18n-key");

const ATTRIBUTE_KEY = /\bdata-i18n(?:-title|-aria-label|-placeholder)?="([^"]+)"/g;
const NAV_KEY = /\bdata-nav="([^"]+)"/g;
const LOOKUP_KEY = /(?:\b_tL\(\)|\btL\(\)|\btL|\btl|\btLang)\[['"]([^'"]+)['"]\]/g;
const STATUS_KEY = /\b_set\w*Status\(\s*['"]([^'"]+)['"]/g;

function readDictionary(html) {
  const start = html.indexOf("var T = {");
  assert.ok(start >= 0, "no `var T = {` in the page");
  const end = html.indexOf("\n  };", start);
  assert.ok(end >= 0, "the T dictionary is not closed by `\\n  };`");
  return vm.runInNewContext(`(${html.slice(start + "var T = ".length, end + 4)})`);
}

function usedKeys(html, jsDir) {
  const keys = new Set();
  for (const [, key] of html.matchAll(ATTRIBUTE_KEY)) keys.add(key);
  for (const [, nav] of html.matchAll(NAV_KEY)) keys.add(`nav-${nav}`);
  const files = fs
    .readdirSync(jsDir)
    .filter((name) => name.endsWith(".js") && !name.endsWith(".min.js"));
  for (const name of files) {
    const source = fs.readFileSync(path.join(jsDir, name), "utf8");
    for (const [, key] of source.matchAll(LOOKUP_KEY)) keys.add(key);
    for (const [, key] of source.matchAll(STATUS_KEY)) keys.add(key);
  }
  return keys;
}

function missingKeys(pageDir) {
  const html = fs.readFileSync(path.join(pageDir, "map.html"), "utf8");
  const T = readDictionary(html);
  const errors = [];
  for (const [lang, other] of [["en", "fr"], ["fr", "en"]]) {
    for (const key of Object.keys(T[lang])) {
      if (!(key in T[other])) errors.push(`'${key}' is in ${lang} but missing in ${other}`);
    }
  }
  for (const key of [...usedKeys(html, path.join(pageDir, "js"))].sort()) {
    if (!(key in T.en) && !(key in T.fr)) errors.push(`'${key}' is used but missing in en and fr`);
  }
  return errors;
}

test("every map-page dictionary key exists in en and fr", () => {
  assert.deepEqual(missingKeys(mapHtmlDir), []);
});

test("a key missing in one language is named", () => {
  assert.deepEqual(missingKeys(fixtureDir), [
    "'title-only-en' is in en but missing in fr",
    "'module-only-key' is used but missing in en and fr",
    "'status-only-key' is used but missing in en and fr",
  ]);
});
