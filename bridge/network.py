"""Bounded HTTPS client: validated IP connection, original Host/SNI, no proxies."""
import http.client
import json
import socket
import ssl
import time
from urllib.parse import urlsplit
from .core import public_addresses, validate_url


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Numeric IP connect bypasses getaddrinfo, avoiding DNS time-of-check races.
        family = socket.AF_INET6 if ":" in self.address else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            raw.connect((self.address, 443))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class HTTPSWebhook:
    def __init__(self, allowed_hosts, connection_factory=PinnedHTTPSConnection):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.connection_factory = connection_factory

    def resolve(self, host):
        if host not in self.allowed_hosts:
            raise OSError("Callback host is not allowed")
        return public_addresses(sorted({row[4][0] for row in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM)}))

    def post(self, url, addresses, raw, headers, *, timeout=10, redirects=False):
        if redirects:
            raise ValueError("Redirects are forbidden")
        host = validate_url(url, self.allowed_hosts)
        addresses = public_addresses(addresses)
        parsed = urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        if len(raw) > 262144:
            raise ValueError("Webhook body too large")
        connection = self.connection_factory(host, addresses[0], timeout)
        deadline = time.monotonic() + timeout
        try:
            connection.request("POST", target, body=raw, headers={
                **headers, "Host": host, "User-Agent": "discord-dot-bridge/0.2.0",
                "Accept": "application/json", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            # Never follow redirects, even to an otherwise permitted host.
            if 300 <= response.status < 400:
                return response.status, {}
            content = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(4096, 65537 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > 65536:
                    raise OSError("Callback response too large")
            try:
                value = json.loads(content) if content else {}
            except (ValueError, UnicodeDecodeError):
                value = {}
            return response.status, value
        except (http.client.HTTPException, ssl.SSLError) as exc:
            raise OSError("Callback transport failed") from exc
        finally:
            connection.close()
