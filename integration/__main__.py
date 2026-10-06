import ipaddress
import socket
import unittest
from unittest.mock import patch

connect = socket.socket.connect
connect_ex = socket.socket.connect_ex
resolve = socket.getaddrinfo


def checked(fn):
    def call(sock, address):
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise AssertionError("External network is forbidden in integration tests")
        return fn(sock, address)
    return call


def local_dns(host, *args, **kwargs):
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise AssertionError("External DNS is forbidden in integration tests")
    return resolve(host, *args, **kwargs)


with patch.object(socket.socket, "connect", checked(connect)), \
     patch.object(socket.socket, "connect_ex", checked(connect_ex)), \
     patch("socket.getaddrinfo", local_dns):
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("integration"))
raise SystemExit(not result.wasSuccessful())
