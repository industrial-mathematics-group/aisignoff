#!/usr/bin/env python3
"""Move inline tags into SIGNOFF.toml, before upgrading to aisignoff 1.0.0rc7.

From 1.0.0rc7 on, aisignoff never reads the content of a file for a declaration: a declaration
comes from SIGNOFF.toml and from git. A file that declared itself in a header comment

    # AI-Generation: G2
    # Human-Review: H2
    ...

would lose that declaration. This script appends one [[annotations]] entry per such file to
SIGNOFF.toml, with exactly the declaration that the file has today (its tags, and the axes they
leave out from the annotation that matches it).

Run it once, at the repository root, with the last release that reads inline tags:

    uv run --with aisignoff==1.0.0rc6 python inline-tags-to-toml.py            # or: --dry-run

Run it before converting SIGNOFF.toml to version 4: on version 3 it writes the levels as the tags
say them, on the scale of version 3, and examples/convert-to-version-4.py then converts them with
the rest of the file. (On version 4 it writes them as they are, on today's scale.) Afterwards the
tag comments mean nothing: delete them when you next touch the files. See docs/migrating.md.
"""
import json
import re
import sys
from pathlib import Path

try:
    from aisignoff import inline
except ImportError:
    sys.exit("this script needs an aisignoff that still reads inline tags: run it with\n"
             "    uv run --with aisignoff==1.0.0rc6 python inline-tags-to-toml.py")
from aisignoff.config import FILENAME, ConfigError, load, load_text
from aisignoff.project import Project, _merge_closest, resolve

ORDER = ("AI-Generation", "Human-Review", "AI-Review", "Assisted-by", "AI-Reviewed-by", "Reviewed-by")


def _literal(path: str) -> str:
    """The glob that matches exactly this path."""
    return "".join("\\" + c if c in "*?\\" else c for c in path)


def main(argv):
    dry = "--dry-run" in argv
    root = Path(".").resolve()
    if not (root / FILENAME).is_file():
        sys.exit(f"no {FILENAME} here: run this at the repository root")
    try:
        config = load(root)
    except ConfigError as e:
        sys.exit(str(e))
    target = root / FILENAME
    old = target.read_text(encoding="utf-8")
    # version 3: the annotations as written, without taking their AI review over to today's scale, so
    # that the entries this writes are on the scale of the file they go into
    as_written = config
    if config.version_3:
        text, n = re.subn(r"(?m)^(\s*version\s*=\s*)3\b", r"\g<1>4", old, count=1)
        if n != 1:
            sys.exit(f"can't find the line 'version = 3' in {FILENAME}")
        try:
            as_written = load_text(text, target)
        except ConfigError as e:
            sys.exit(str(e))
    block, tagged, broken = [], [], []
    for path in Project(root).files():
        try:
            found = inline.parse(root / path)
        except OSError:
            found = None
        if found is None:
            continue
        annotation = config.match(path)
        if annotation is not None and annotation.precedence == "override":
            continue   # the tags never counted
        d = resolve(root, config, path)
        if d.problems:
            broken.append(f"{path}: {'; '.join(d.problems)}")
            continue
        if config.version_3:
            # the tags as written (inline.parse doesn't take them over), the rest from the annotation as written
            written = as_written.match(path)
            values = _merge_closest(found, written.declaration() if written else None).as_dict()
        else:
            values = d.as_dict()
        block += ["", "[[annotations]]   # was declared by inline tags", f"path = {json.dumps(_literal(path))}"]
        for key in ORDER:
            v = values.get(key)
            if v:
                block.append(f"{key} = {json.dumps(v if isinstance(v, str) or len(v) != 1 else v[0], ensure_ascii=False)}")
        tagged.append(path)
    if broken:
        print("These files have inline tags that aren't a valid declaration. Declare them by hand "
              "(aisignoff annotate):\n" + "".join(f"  {b}\n" for b in broken))
    if not tagged:
        print("No file is declared by inline tags: nothing to do.")
        return
    new = old + ("" if old.endswith("\n") else "\n") + "\n".join(block) + "\n"
    try:
        after = load_text(new, target)
    except ConfigError as e:
        sys.exit(f"the result wouldn't be a valid {FILENAME} (nothing was written): {e}")
    wrong = [p for p in tagged if after.match(p).declaration().as_dict() | {"source": ""}
             != resolve(root, config, p).as_dict() | {"source": ""}]
    if wrong:
        sys.exit("the result wouldn't declare these files as their tags do (nothing was written): " + ", ".join(wrong))
    print("\n".join(block).lstrip("\n"))
    if not dry:
        target.write_text(new, encoding="utf-8")
        print(f"\nAppended {len(tagged)} annotation(s) to {FILENAME}.")
    if config.version_3:
        print(f"\n{FILENAME} is version 3, so these levels are on its scale. Convert it to version 4 now, "
              "with examples/convert-to-version-4.py, which takes them over with the rest of the file.")
    print("\nThe tag comments in these files mean nothing from aisignoff 1.0.0rc7 on; delete them when "
          "you next touch the files:\n" + "".join(f"  {p}\n" for p in tagged), end="")


if __name__ == "__main__":
    main(sys.argv[1:])
