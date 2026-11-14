# Declaring files

A file's declaration comes from `SIGNOFF.toml`, from tags in the file itself, or from both. With [line-level declarations](history.md), this file-level declaration is the fallback for lines that git doesn't declare.

## Annotations in SIGNOFF.toml

`SIGNOFF.toml` in the repository root maps paths to declarations:

```toml
version = 3
exclude = ["reviews/**"]

[[annotations]]
path = "**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A0"
Reviewed-by = "Jane Doe"

[[annotations]]
path = ["results/**", "figures/*.pdf"]
AI-Generation = "G2"
Human-Review = "H1"
AI-Review = "A1"
Assisted-by = "Claude Opus 5.5 (Anthropic)"
AI-Reviewed-by = "Claude Opus 5.5 (Anthropic), self-check by the generating session"
Reviewed-by = "Jane Doe"
```

- **The last matching annotation wins.** Put the general default first and the exceptions after it.
- **`path`** is one glob or a list, relative to the repository root. `*` stays within a folder, `**` crosses folders (`**/` also matches no folder), `?` is one character, and `\*`, `\?`, `\\` match those characters literally.
- **Names** (`Assisted-by`, `Reviewed-by`, `AI-Reviewed-by`) take a string or a list.
- **`precedence`** decides between the annotation and inline tags, [below](#which-one-wins).

Write annotations by hand or with `aisignoff annotate`:

```bash
aisignoff annotate results/ -g G2 -H H1 -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), self-check by the generating session" \
    --reviewed-by "Jane Doe"
```

Each call appends one annotation for all the paths it's given. It refuses an incomplete declaration or one below the [policy](levels.md#minimum-levels), and leaves `SIGNOFF.toml` unchanged if the result wouldn't be valid. Existing files are matched exactly (even with `*` in their name), a folder becomes `folder/**`, and anything else is a glob, which must be quoted and is read relative to the current directory. Paths outside the project are refused.

## Inline tags

Text files can declare themselves in a comment within their first 30 lines:

```python
# AI-Generation: G2
# Human-Review: H2
# AI-Review: A2
# Assisted-by: Claude Opus 5.5 (Anthropic)
# AI-Reviewed-by: GPT-5 (OpenAI), fresh review session
# Reviewed-by: Jane Doe
```

`aisignoff annotate FILE … --inline` writes or updates this block. It puts it after a shebang, an encoding line, an XML declaration or Markdown front matter, leaves the rest of the file untouched (line endings and byte-order mark included), and refuses if the block wouldn't fit into the first 30 lines.

So that documentation is never mistaken for a declaration, tags count only:

- **in the file type's own comment syntax**: `#` (Python, Julia, R, shell, YAML, TOML, …), `//` or `/* */` (C-like languages, JavaScript, Rust, Go, Typst, …), `%` (LaTeX, MATLAB), `--` (Lua, SQL, Haskell), `;` (Lisp, INI), `<!-- -->` (Markdown, HTML, XML, SVG) and `(* *)` (OCaml). File types without a known syntax, such as `.txt`, `.csv`, `.json`, notebooks or `LICENSE`, can only be declared in `SIGNOFF.toml`;
- **at the start of a line**: only the `*` continuation lines of a `/* */` comment may be indented, so indented examples in docstrings are ignored. Fenced code blocks in Markdown are skipped;
- **as a contiguous block that contains a valid level line**, such as `AI-Generation: G2`. A comment that explains the keys (`# AI-Generation: G0-G3`) is ignored. `TODO` counts as a level here, so an unfilled block is found and fails `lint`.

## Which one wins

By default (`precedence = "closest"`), a file's inline tags win over its annotation, **axis by axis**:

- The axes are generation (`AI-Generation` with `Assisted-by`), human review (`Human-Review` with `Reviewed-by`) and AI review (`AI-Review` with `AI-Reviewed-by`).
- An axis counts as declared inline when its level line is there; the axes the block leaves out come from the matching annotation. A file can, for example, declare only its AI review inline.
- A name line without its level line, such as `Assisted-by` without `AI-Generation`, is an error.

With `precedence = "override"` on the annotation, the annotation alone counts. With `[history]`, such files are also never resolved line by line, which suits vendored or generated code.

## Which files are checked

- **In a git repository:** tracked files plus untracked files that aren't ignored, so `.gitignore` is respected. If git can't be run there, aisignoff stops rather than ignoring `.gitignore`.
- **Outside git:** every file below the root.
- **Never:** `SIGNOFF.toml` itself, `SIGNOFF.snapshot.json`, and anything that matches `exclude`.

!!! tip
    Exclude the folder of committed AI reviews (`reviews/` by convention): the reviews need no declaration themselves.
