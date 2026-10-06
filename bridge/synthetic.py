"""Clearly marked fixtures. These are not credentials or working endpoints."""
import json

OWNER = "111111111111111111"
BOT = "222222222222222222"
CHANNEL = "333333333333333333"
MESSAGE = "444444444444444444"
BEARER = "SYNTHETIC-ONLY-NOT-A-CREDENTIAL-000000"
SECRET = "whsec_" + "QUFB" * 8  # 24 fixed test bytes; never suitable for live use
URL = "https://callback.example.test/events"
NOW = 1791244800.0


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class FakeWebhook:
    def __init__(self):
        self.calls = []
        self.addresses = ["8.8.8.8"]  # Validation input only. No socket is opened.
        self.status = 200
        self.challenge_ok = True

    def resolve(self, hostname):
        return self.addresses

    def post(self, url, addresses, body, headers, *, timeout, redirects):
        assert redirects is False and timeout == 10
        self.calls.append((url, addresses, body, headers))
        payload = json.loads(body)
        if payload.get("type") == "verification":
            return self.status, {"challenge": payload["challenge"] if self.challenge_ok else "wrong"}
        return self.status, {}


class FakeDiscord:
    def __init__(self):
        self.sent = []
        self.timeout = False

    def send_dm(self, channel, owner, payload):
        assert owner == OWNER and channel == CHANNEL
        self.sent.append(payload)
        if self.timeout:
            raise TimeoutError


def subscription():
    return {"name": "discord.dm.created", "arguments": {"owner_id": OWNER},
            "delivery": {"mode": "webhook", "url": URL, "secret": SECRET}, "cursor": None}


def dispatch(mid=MESSAGE):
    from .core import iso
    return {"op": 0, "t": "MESSAGE_CREATE", "s": 1, "d": {
        "id": mid, "channel_id": CHANNEL, "author": {"id": OWNER, "bot": False},
        "content": "Synthetic owner message", "timestamp": iso(NOW), "type": 0}}
