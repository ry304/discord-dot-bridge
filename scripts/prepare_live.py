"""Prepare disabled private live config; never read a bot token or start a service."""
import argparse
import json
import os
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--approved-callback-host", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    private = root / "private"
    if not root.is_absolute() or private.resolve() != private or private.stat().st_mode & 0o077:
        parser.error("Private deployment directory required")
    host = args.approved_callback_host
    if not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host or len(host) > 253:
        parser.error("Exact reviewed callback hostname required")
    if (private / "probe" / "callback.hostname").read_text().strip() != host:
        parser.error("Approved hostname must match the authenticated probe")
    setup = json.loads((private / "setup.guild.json").read_text())
    discovery = json.loads((private / "discovery.json").read_text())
    subject = (private / "owner.subject").read_text().strip()
    if not subject or len(subject) > 256 or any(c.isspace() for c in subject):
        parser.error("Valid owner subject required")
    config = {key: setup[key] for key in ("owner_discord_id", "bot_discord_id", "discord_mode",
                                         "discord_guild_id", "discord_channel_id")}
    config.update(resource=discovery["resource"], oauth_issuer=discovery["oauth_issuer"],
        oauth_subject=subject, callback_hosts=[host], jwks_file="/private/auth0-public-jwks.json",
        enabled_file="/state/live.enabled", discord_bot_token_file="/private/discord-bot.token",
        state_path="/state/bridge.sqlite3")
    state = private / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    if state.is_symlink() or state.stat().st_mode & 0o077:
        parser.error("Private state directory required")
    for path, value in ((private / "live.json", json.dumps(config, indent=2) + "\n"),
                        (state / "live.enabled", "disabled\n")):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
    print("Private live configuration prepared; activation disabled; bot token not read.")


if __name__ == "__main__":
    main()
