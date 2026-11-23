"""Cross-platform verification for new source-pinned protocols."""

import hashlib
import subprocess
from pathlib import Path

from agent_reliability_lab.opsdesk.fixtures import digest


def committed_source(source: Path, commit: str) -> tuple[str, str]:
    """Verify working source and lock against the checked-out Git blobs, allowing CRLF."""

    def git(directory: Path, *args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(directory), *args])

    root = Path(git(source, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    if git(root, "rev-parse", "HEAD").decode("ascii").strip() != commit:
        raise ValueError("source commit differs from the checked-out Git commit")
    source = source.resolve()
    subtree = source.relative_to(root.resolve()).as_posix() + "/"
    index = {}
    for entry in git(root, "ls-tree", "-rz", commit, "--", subtree, "uv.lock").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if path == "uv.lock" or path.endswith(".py"):
            mode, kind, oid = metadata.decode("ascii").split()
            if mode not in {"100644", "100755"} or kind != "blob":
                raise ValueError("frozen source must use regular committed files")
            index[path] = oid
    paths = {path.relative_to(root).as_posix() for path in source.rglob("*.py")} | {"uv.lock"}
    if set(index) != paths:
        raise ValueError("working Python source inventory differs from the frozen commit")
    hashes = {}
    for name, oid in index.items():
        path = root / name
        if path.resolve() != path or not path.is_file():
            raise ValueError("working source must use regular files inside the checkout")
        data = path.read_bytes().replace(b"\r\n", b"\n")
        # Check the exact canonical bytes against the committed object ID. The
        # protocol separately pins a SHA-256 digest of paths and source content.
        actual = hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
        if actual != oid:
            raise ValueError(f"working file differs from committed source: {name}")
        hashes[name] = hashlib.sha256(data).hexdigest()
    lock_hash = hashes.pop("uv.lock")
    return digest({name.removeprefix(subtree): h for name, h in hashes.items()}), lock_hash
