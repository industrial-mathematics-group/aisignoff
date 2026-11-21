#!/bin/sh
# Rebuilds src/aisignoff/highlight.min.js, the highlight.js bundle that 'aisignoff report --html --with-source'
# inlines for the syntax colours of the line view. Needs node and npm; run from the repository root.
# Keep LANGUAGES in step with LANGUAGE_BY_EXT and LANGUAGE_BY_NAME in src/aisignoff/report.html.
set -eu
VERSION=11.11.1
LANGUAGES="python julia fortran matlab latex ini yaml json bash markdown c cpp r rust go javascript typescript xml css makefile cmake dockerfile sql diff"
OUT="$PWD/src/aisignoff/highlight.min.js"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
npm init -y >/dev/null
npm install --silent "highlight.js@$VERSION" esbuild@0.24.0
{
  echo "import hljs from 'highlight.js/lib/core';"
  for l in $LANGUAGES; do echo "import l_$l from 'highlight.js/lib/languages/$l'; hljs.registerLanguage('$l', l_$l);"; done
  echo "globalThis.hljs = hljs;"
} > entry.mjs
npx esbuild entry.mjs --bundle --minify --format=iife --legal-comments=none --outfile=bundle.js
{
  printf '/*! highlight.js %s (%s), https://highlightjs.org\n' "$VERSION" "$LANGUAGES"
  cat node_modules/highlight.js/LICENSE
  printf '*/\n'
  # the bundle is inlined in a <script> element: '<!--' and '<script' only occur in its regular
  # expressions, where \x3C is the same character and can't change how the HTML parser reads the element
  sed -e 's/<!--/\\x3C!--/g' -e 's/<script/\\x3Cscript/g' -e 's/<\/script/\\x3C\/script/g' bundle.js
  printf '\n'
} > "$OUT"
if grep -qi -e '<!--' -e '<script' -e '</script' "$OUT"; then echo "highlight.min.js still contains a script-breaking sequence" >&2; exit 1; fi
echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
