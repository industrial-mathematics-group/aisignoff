# Inline tags

Source files and documents can carry their declaration in a comment within their first 30 lines:

```julia
# AI-Generation: G2
# Human-Review: H2
# AI-Review: A2
# Assisted-by: Claude Opus 5.5 (Anthropic)
# AI-Reviewed-by: Claude Opus 5.5 (Anthropic), fresh review session
# Reviewed-by: Jane Doe
```

`aisignoff annotate FILE … --inline` writes or updates these lines for you.

With [line-by-line declarations](history.md) and a [snapshot](history.md#freezing-the-levels-aisignoff-freeze), the tags are the file-level declaration that undeclared lines took when the snapshot was made. Editing them later doesn't change those frozen lines: raise a reviewed file with `aisignoff attest` instead.

## What counts as a declaration

Three rules keep documentation from being mistaken for a declaration.

**The file type's own comment syntax:**

| Comment | File types |
|---|---|
| `#` | Julia, Python, YAML, shell, … |
| `//` or `/* */` | C-like languages |
| `%` | LaTeX |
| `<!-- -->` | Markdown and HTML |

Fenced code blocks in Markdown are skipped. File types without a known comment syntax, such as `.txt`, `.csv`, `.json`, notebooks or `LICENSE`, can only be declared in [`SIGNOFF.toml`](signoff-toml.md).

**Start of the line:** the comment must start the line. Only `*` continuation lines of a `/* */` comment may be indented, so indented examples in docstrings are ignored.

**A contiguous block with a valid level:** tag lines count only as a block of adjacent lines that contains a valid level line, such as `AI-Generation: G2` or `AI-Review: A0`.

- A comment that merely explains the keys, like `#   AI-Generation: G0-G3`, is ignored.
- `TODO` counts as a level here, so a block with an unfilled TODO is found and fails `lint`.

## Writing tags with `--inline`

- **Placement:** after a shebang, an encoding line, an XML declaration or (in Markdown) YAML front matter.
- **The rest of the file stays untouched,** including line endings and a byte-order mark.
- **Safety:** it refuses if the block wouldn't fit into the first 30 lines. It reads the result back and restores the file if the tags couldn't be read.

## Precedence

A file's inline tags win over `SIGNOFF.toml` ("closest"), unless the matching annotation sets `precedence = "override"`. This works per axis:

- **The axes** are generation (`AI-Generation` with `Assisted-by`), human review (`Human-Review` with `Reviewed-by`) and AI review (`AI-Review` with `AI-Reviewed-by`).
- **An axis counts as declared inline** when its level line is present. Any axis the inline block leaves out comes from the matching annotation.
- **A name line on its own,** such as `Assisted-by` without `AI-Generation`, is an error.

For example, a file can declare only its AI review inline and take generation and human review from `SIGNOFF.toml`.
