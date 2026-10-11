import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../apps/web/", import.meta.url));
const require = createRequire(path.join(root, "package.json"));
const ts = require("typescript");
const files = [];

function scan(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (["node_modules", ".next", "coverage"].includes(entry.name)) continue;
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (/\.(tsx?|mts)$/.test(file) && !file.endsWith(".d.ts"))
      files.push(file);
  }
}
scan(root);

const config = ts.readConfigFile(
  path.join(root, "tsconfig.json"),
  ts.sys.readFile,
);
if (config.error)
  throw new Error(
    ts.flattenDiagnosticMessageText(config.error.messageText, "\n"),
  );
const options = ts.convertCompilerOptionsFromJson(
  config.config.compilerOptions,
  root,
).options;
const fileSet = new Set(files);
const graph = new Map();
const errors = [];

for (const file of files) {
  const ast = ts.createSourceFile(
    file,
    fs.readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
  );
  const imports = [];
  function visit(node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      imports.push(node.moduleSpecifier.text);
    }
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      imports.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  const dependencies = [];
  for (const specifier of imports) {
    const resolved = ts.resolveModuleName(
      specifier,
      file,
      options,
      ts.sys,
    ).resolvedModule;
    if (!resolved) {
      if (
        /\.(css|svg|png|jpg)$/.test(specifier) &&
        fs.existsSync(path.resolve(path.dirname(file), specifier))
      )
        continue;
      if (specifier.startsWith(".") || specifier.startsWith("@/")) {
        errors.push(
          `${path.relative(root, file)}: unresolved import ${specifier}`,
        );
      }
      continue;
    }
    const dependency = path.resolve(resolved.resolvedFileName);
    if (fileSet.has(dependency)) dependencies.push(dependency);
    const local = path.relative(root, file).split(path.sep)[0];
    if (
      ["lib", "types"].includes(local) &&
      ["app", "components", "hooks"].includes(
        path.relative(root, dependency).split(path.sep)[0],
      )
    ) {
      errors.push(
        `${path.relative(root, file)}: UI dependency in a foundational module`,
      );
    }
  }
  graph.set(file, dependencies);
}

const entries = files.filter((file) => {
  const relative = path.relative(root, file).split(path.sep).join("/");
  return (
    (relative.startsWith("app/") &&
      /\/(page|layout|route)\.tsx?$/.test(relative)) ||
    relative.startsWith("tests/") ||
    /^(middleware|vitest\.config|next\.config)\.(ts|mts)$/.test(relative)
  );
});
const seen = new Set();
const active = [];
function follow(file) {
  if (active.includes(file)) {
    errors.push(
      `Import cycle: ${[...active.slice(active.indexOf(file)), file].map((f) => path.relative(root, f)).join(" -> ")}`,
    );
    return;
  }
  if (seen.has(file)) return;
  seen.add(file);
  active.push(file);
  for (const dependency of graph.get(file) ?? []) follow(dependency);
  active.pop();
}
entries.forEach(follow);
for (const file of files) {
  if (!seen.has(file))
    errors.push(`Unreachable module: ${path.relative(root, file)}`);
}
if (errors.length)
  throw new Error(`Web architecture check failed:\n${errors.join("\n")}`);
console.log(
  `PASS: ${files.length} web modules; no dead modules, import cycles or reversed UI dependencies`,
);
