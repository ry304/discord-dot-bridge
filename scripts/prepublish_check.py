"""Conservative tracked-source hygiene check; not a substitute for review."""
import re
import subprocess
from pathlib import Path

files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
blocked = []
for name in filter(None, files):
    path = Path(name)
    if any(part in {".venv", "state", "secrets", "__pycache__"} for part in path.parts) or \
            path.name.startswith(("config.local", ".env")) or path.suffix in {".sqlite3", ".db", ".pem", ".key", ".log"}:
        blocked.append(name + ": private file category")
        continue
    content = path.read_text(encoding="utf-8")
    for pattern in [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", r"\bgh[pousr]_[A-Za-z0-9]{20,}",
                    r"\bgithub_pat_[A-Za-z0-9_]{20,}", r"\bsk-proj-[A-Za-z0-9_-]{20,}"]:
        if re.search(pattern, content):
            blocked.append(name + ": credential-shaped content")
    # Public fixtures may contain only visibly synthetic Discord-sized IDs.
    for value in re.findall(r"(?<!\d)\d{17,20}(?!\d)", content):
        if len(set(value)) != 1:
            blocked.append(name + ": non-synthetic numeric identity")
if blocked:
    raise SystemExit("Publication check failed:\n" + "\n".join(blocked))
print("PASS: tracked files contain no private file categories, credential patterns or non-synthetic numeric IDs.")
