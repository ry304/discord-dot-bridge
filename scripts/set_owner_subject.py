"""USER-RUN private owner identity handoff; never prints the supplied subject."""
import argparse
import getpass
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="New owner subject file in an existing private directory")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("Use an interactive terminal so the identifier is never echoed")
    path = Path(args.path)
    if (not path.is_absolute() or not path.parent.is_dir() or path.parent.is_symlink()
            or (os.name != "nt" and path.parent.stat().st_mode & 0o077)):
        parser.error("Use an absolute path in an existing private directory")
    if path.exists() or path.is_symlink():
        parser.error("File already exists; operator review required before replacing owner binding")
    subject = getpass.getpass("Verified Auth0 owner User ID (hidden): ").strip()
    if not subject or len(subject) > 256 or any(c.isspace() for c in subject):
        parser.error("Invalid user identifier")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(subject + "\n")
        file.flush()
        os.fsync(file.fileno())
    print("Private owner identifier saved; its value was not displayed.")


if __name__ == "__main__":
    main()
