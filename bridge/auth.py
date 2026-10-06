"""OAuth resource-server verification; authorization/PKCE is handled by an IdP."""
import json
from pathlib import Path
import jwt

SCOPE = "discord:bridge"


class AuthError(Exception):
    pass


class OAuthVerifier:
    def __init__(self, *, issuer, resource, subject, jwks_file, enabled_file):
        self.issuer, self.resource, self.subject = issuer, resource, subject
        self.jwks_file, self.enabled_file = Path(jwks_file), Path(enabled_file)

    def enabled(self):
        try:
            return self.enabled_file.read_text().strip() == "enabled"
        except OSError:
            return False

    def verify(self, authorization):
        if not self.enabled() or not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise AuthError("Authentication required")
        token = authorization[7:]
        if not token or len(token) > 16384:
            raise AuthError("Invalid access token")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError
            if header.get("typ", "JWT").lower() not in ("jwt", "at+jwt"):
                raise ValueError
            raw = self.jwks_file.read_bytes()
            if len(raw) > 65536:
                raise ValueError
            keys = json.loads(raw)["keys"]
            choices = [k for k in keys if k.get("kid") == header["kid"] and k.get("kty") == "RSA"
                       and k.get("use", "sig") == "sig" and k.get("alg", "RS256") == "RS256"]
            if len(choices) != 1:
                raise ValueError
            key = jwt.PyJWK.from_dict(choices[0], algorithm="RS256").key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.resource,
                                issuer=self.issuer, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            if claims["sub"] != self.subject or SCOPE not in str(claims.get("scope", "")).split():
                raise ValueError
            # Short, refreshable access tokens bound both tool and event authority.
            if claims["exp"] - claims["iat"] > 3600:
                raise ValueError
            return claims
        except (jwt.PyJWTError, ValueError, OSError, KeyError, TypeError):
            raise AuthError("Invalid access token") from None

    def metadata(self):
        return {"resource": self.resource, "authorization_servers": [self.issuer],
                "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]}
