import assert from "node:assert/strict";
import test from "node:test";

import { formatZoom } from "../html/js/utils.js";

test("formatZoom keeps at most two decimals without trailing zeros", () => {
  assert.equal(formatZoom(12), "12");
  assert.equal(formatZoom(12.5), "12.5");
  assert.equal(formatZoom(12.75), "12.75");
  assert.equal(formatZoom(12.333333), "12.33");
});
