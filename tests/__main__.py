import unittest
from unittest.mock import patch

with patch("socket.socket", side_effect=AssertionError("Network forbidden during tests")), \
     patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden during tests")):
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
raise SystemExit(not result.wasSuccessful())
