"""Offline demo by default; live service requires explicit opt-in and secure setup."""
import argparse
import tempfile
from pathlib import Path
from .core import Bridge
from .synthetic import (OWNER, BOT, BEARER, MESSAGE, Clock, FakeWebhook,
                        FakeDiscord, subscription, dispatch)


def main():
    parser = argparse.ArgumentParser(description="Offline Discord-to-dot protocol demo")
    parser.add_argument("command", choices=["demo", "validate-config", "serve"])
    parser.add_argument("--config")
    parser.add_argument("--enable-network", action="store_true")
    parser.add_argument("--register-commands", action="store_true",
                        help="Explicitly register the dedicated app's owner-only global commands")
    args = parser.parse_args()
    if args.command != "demo":
        from .config import Config
        if not args.config:
            parser.error("--config is required")
        config = Config.load(args.config)
        if args.command == "validate-config":
            print("PASS: configuration structure validated; no credentials read or connections made.")
            return
        if not args.enable_network:
            parser.error("serve requires --enable-network after setup approval")
        import asyncio
        from .runtime import serve
        try:
            asyncio.run(serve(config, register_commands=args.register_commands))
        except KeyboardInterrupt:
            pass
        except Exception:
            parser.exit(1, "Bridge stopped: verify private configuration, credentials and connectivity.\n")
        return
    with tempfile.TemporaryDirectory() as temp:
        hook, discord, clock = FakeWebhook(), FakeDiscord(), Clock()
        bridge = Bridge(Path(temp) / "synthetic.sqlite3", owner_id=OWNER, bot_id=BOT,
                        bearer=BEARER, callback_hosts=["callback.example.test"],
                        webhook=hook, discord=discord, clock=clock)
        def call(method, params):
            response = bridge.rpc({"jsonrpc": "2.0", "id": 1, "method": method,
                                   "params": params}, "Bearer " + BEARER)
            assert "error" not in response, response
            return response["result"]
        call("server/discover", {})
        call("events/subscribe", subscription())
        assert bridge.ingest(dispatch(), channel_type=1, recipient_id=OWNER)
        bridge.pump()
        result = call("tools/call", {"name": "discord_reply", "arguments": {
            "message_id": MESSAGE, "text": "Synthetic response from the existing dot."}})
        assert not result["isError"]
        call("events/unsubscribe", subscription())
        bridge.close()
    print("PASS: synthetic authenticated discovery, subscription, signed verification, "
          "owner DM, event delivery, reply and unsubscribe. No network or model calls.")


if __name__ == "__main__":
    main()
