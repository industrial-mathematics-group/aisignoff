"""Compare diff units with the two checked-out file versions."""
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

helpers = runpy.run_path(str(Path(sys.argv[2]).resolve()))
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def examine(tool, encoded):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        new_repo(root)
        filename = "notes.txt"
        if encoded:
            (root / ".gitattributes").write_text("notes.txt working-tree-encoding=UTF-16LE\n")
        encoding = "utf-16le" if encoded else "utf-8"
        path = root / filename
        path.write_text("original\nkeep one\nkeep two\n", encoding=encoding)
        commit(root, "Initial notes", "H1")
        run(root, "git", "switch", "-qc", "feature")
        path.write_text("changed\nkeep one\nkeep two\n", encoding=encoding)
        commit(root, "Change first line", "H3")
        data = json.loads(run(root, tool, "diff", "main", "--json", "--files").stdout)
        row = next(row for row in data["rows"] if row["name"] == filename)
        print(f"{encoding}: added={row['added']}, removed={row['removed']}")
        print("Removed H levels:", row["levels_removed"]["Human-Review"])


def landed(tool):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        new_repo(root)
        path = root / "data"
        tail = b"same line 2\nsame line 3\n"
        path.write_bytes(b"\x00binary\n" + tail)
        commit(root, "Add binary", "H1")
        path.write_bytes(b"new line 1\n" + tail)
        commit(root, "Replace binary with text on main", "H3")
        data = json.loads(run(root, tool, "report", "--json").stdout)
        file = next(entry for entry in data["files"] if entry["path"] == path.name)
        print("Landed binary-to-text provenance:", [(p["runs"], p["Human-Review"]) for p in file["parts"]])


if __name__ == "__main__":
    for tool in (str(Path(sys.executable).with_name("aisignoff")), str(Path(sys.argv[1]).resolve())):
        print(run(Path.cwd(), tool, "--version").stdout.strip())
        for encoded in (False, True):
            examine(tool, encoded)
        landed(tool)
