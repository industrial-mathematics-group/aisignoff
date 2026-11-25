"""A stand-in for Git LFS in probe_units.py: 'clean' stores the content in a folder and gives git a
three-line text pointer, 'smudge' gives the content back.

usage: python ptr_filter.py clean|smudge STORE"""
import hashlib
import sys
from pathlib import Path

mode, store = sys.argv[1], Path(sys.argv[2])
data = sys.stdin.buffer.read()
HEAD = b"version https://example.invalid/ptr/v1\n"
if mode == "clean":
    if data.startswith(HEAD):
        sys.stdout.buffer.write(data)
    else:
        oid = hashlib.sha256(data).hexdigest()
        store.mkdir(parents=True, exist_ok=True)
        (store / oid).write_bytes(data)
        sys.stdout.buffer.write(HEAD + f"oid sha256:{oid}\nsize {len(data)}\n".encode())
else:
    oid = data.split(b"sha256:")[1].split(b"\n")[0].decode() if data.startswith(HEAD) else None
    sys.stdout.buffer.write((store / oid).read_bytes() if oid and (store / oid).exists() else data)
