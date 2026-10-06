"""Strict file-based configuration. Validation never reads credentials or connects."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    owner_discord_id: str
    bot_discord_id: str
    resource: str
    oauth_issuer: str
    oauth_subject: str
    callback_hosts: list[str]
    jwks_file: str
    enabled_file: str
    discord_bot_token_file: str
    state_path: str
    listen_host: str = "127.0.0.1"
    listen_port: int = 8765
    allowed_origins: list[str] = None

    @classmethod
    def load(cls, path):
        raw = Path(path).read_bytes()
        if len(raw) > 16384:
            raise ValueError("Configuration too large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Configuration must be an object")
        config = cls(**data)
        for value in (config.owner_discord_id, config.bot_discord_id):
            if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 17 <= len(value) <= 20:
                raise ValueError("Numeric Discord IDs are required")
        if config.owner_discord_id == config.bot_discord_id:
            raise ValueError("Owner and bot must differ")
        for value in (config.resource, config.oauth_issuer):
            u = urlsplit(value)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in (443, None):
                raise ValueError("OAuth URLs must be canonical HTTPS URLs")
        if urlsplit(config.resource).path != "/mcp":
            raise ValueError("Resource must end in /mcp")
        if not isinstance(config.oauth_subject, str) or not config.oauth_subject or "REPLACE" in config.oauth_subject:
            raise ValueError("Owner OAuth subject must be configured")
        if not isinstance(config.callback_hosts, list) or not config.callback_hosts or len(config.callback_hosts) > 8:
            raise ValueError("Explicit callback hosts required")
        for host in config.callback_hosts:
            if not isinstance(host, str) or not host or host != host.lower() or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host):
                raise ValueError("Callback hosts must be exact DNS names")
        if config.listen_host != "127.0.0.1":
            raise ValueError("This release binds only to loopback; use an approved HTTPS proxy")
        if type(config.listen_port) is not int or not 1024 <= config.listen_port <= 65535:
            raise ValueError("Invalid listen port")
        if config.allowed_origins is not None and (not isinstance(config.allowed_origins, list)
                or any(not isinstance(x, str) or not x.startswith("https://") for x in config.allowed_origins)):
            raise ValueError("Invalid Origin allowlist")
        for field in ("jwks_file", "enabled_file", "discord_bot_token_file", "state_path"):
            if not isinstance(getattr(config, field), str) or not Path(getattr(config, field)).is_absolute():
                raise ValueError("Runtime file paths must be absolute")
        return config


def read_secret(path):
    file = Path(path)
    if file.is_symlink() or file.stat().st_size > 16384:
        raise ValueError("Invalid secret file")
    if os.name != "nt" and file.stat().st_mode & 0o077:
        raise ValueError("Secret file must be private to its owner")
    secret = file.read_text().strip()
    if not secret or any(c.isspace() for c in secret) or secret.startswith("SYNTHETIC"):
        raise ValueError("Invalid bot token file")
    return secret
