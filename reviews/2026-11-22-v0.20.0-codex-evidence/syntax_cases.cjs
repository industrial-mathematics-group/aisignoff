// Run with Node from an aisignoff v0.20.0 checkout. The review ran the same function in V8.
function syntaxCases(bundle, template) {
  const start = template.indexOf("const LANGUAGE_BY_EXT");
  const stop = template.indexOf("const colouredLine");
  if (start < 0 || stop <= start) throw new Error("Syntax highlighter functions not found");
  const evaluate = new Function("const window = globalThis;\n" + bundle + "\n" +
    template.slice(start, stop) + `
    return [
      ["plain", ["#!/usr/bin/env python3", "print(1)"]],
      ["flagged", ["#!/usr/bin/env -S python3 -X pycache_prefix=/tmp/sh", "print(1)"]],
      ["multiline.py", ['s = """hello', 'world"""']],
    ].map(([path, lines]) => ({
      path,
      language: languageOf(path, lines[0]),
      lines: highlightLines({ path }, lines),
    }));
  `);
  return evaluate();
}

if (typeof require !== "undefined" && require.main === module) {
  const fs = require("node:fs");
  const bundle = fs.readFileSync("src/aisignoff/highlight.min.js", "utf8");
  const template = fs.readFileSync("src/aisignoff/report.html", "utf8");
  console.log(JSON.stringify(syntaxCases(bundle, template), null, 2));
}
