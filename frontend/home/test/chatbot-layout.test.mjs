import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const jsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../html/js");
const read = (name) => fs.readFileSync(path.join(jsDir, name), "utf8");

const NAV_HEIGHT_PROPERTY = "--sdss-nav-height";
const OVERRIDDEN_SELECTORS = ["#root", ".app-container", ".app", ".right", ".center", ".landing-container"];

test("nav-inject.js publishes the nav height that chatbot-bridge.js subtracts", () => {
  assert.match(read("nav-inject.js"), new RegExp(`setProperty\\(\\s*'${NAV_HEIGHT_PROPERTY}'`));
  assert.ok(
    read("chatbot-bridge.js").includes(`var(${NAV_HEIGHT_PROPERTY}, 0px)`),
    `chatbot-bridge.js does not read var(${NAV_HEIGHT_PROPERTY}, 0px)`,
  );
});

test("chatbot-bridge.js overrides every upstream full-height container", () => {
  const bridge = read("chatbot-bridge.js");
  for (const selector of OVERRIDDEN_SELECTORS) {
    assert.ok(new RegExp(`['+,]${selector.replace(".", "\\.")}[,{]`).test(bridge), `${selector} not overridden`);
  }
});
