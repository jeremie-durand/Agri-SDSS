// Links every non-minified .js file of html/js as an ES module with Node's real
// linker, without evaluating any of them, so a missing export or module fails
// here the way it fails in the browser. Classic scripts in that directory are
// parsed in module mode too. Needs --experimental-vm-modules (see `make test-home`).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const mapJsDir = path.resolve(here, "../html/js");
const brokenFixtureDir = path.resolve(here, "fixtures/broken-imports");
const MIN_LINKED_MODULES = 15;

async function linkModules(dir) {
  const context = vm.createContext({});
  const modules = new Map();
  const load = (file) => {
    if (!modules.has(file)) {
      const source = fs.readFileSync(file, "utf8");
      modules.set(file, new vm.SourceTextModule(source, { identifier: file, context }));
    }
    return modules.get(file);
  };
  const resolve = (specifier, referencing) => {
    const importer = path.basename(referencing.identifier);
    const missing = new Error(`missing module ${specifier} (imported by ${importer})`);
    if (!specifier.startsWith("./") && !specifier.startsWith("../")) throw missing;
    const target = path.resolve(path.dirname(referencing.identifier), specifier);
    if (!fs.existsSync(target)) throw missing;
    return load(target);
  };

  const files = fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".js") && !name.endsWith(".min.js"))
    .sort();
  const errors = [];
  let linked = 0;
  for (const name of files) {
    const module = load(path.join(dir, name));
    if (module.status === "errored") {
      errors.push(`${name}: ${module.error.message}`);
      continue;
    }
    if (module.status !== "unlinked") {
      linked++;
      continue;
    }
    try {
      await module.link(resolve);
      linked++;
    } catch (error) {
      errors.push(`${name}: ${error.message}`);
    }
  }
  return { errors, linked };
}

test("every map module links", async () => {
  const { errors, linked } = await linkModules(mapJsDir);
  assert.deepEqual(errors, []);
  assert.ok(linked >= MIN_LINKED_MODULES, `only ${linked} modules linked`);
});

test("a missing export and a missing module are both reported", async () => {
  const { errors } = await linkModules(brokenFixtureDir);
  assert.equal(errors.length, 2, errors.join("\n"));
  assert.match(
    errors.find((e) => e.startsWith("imports-missing-export.js")) ?? "",
    /does not provide an export named 'absent'/,
  );
  assert.match(
    errors.find((e) => e.startsWith("imports-missing-module.js")) ?? "",
    /missing module \.\/does-not-exist\.js/,
  );
});
