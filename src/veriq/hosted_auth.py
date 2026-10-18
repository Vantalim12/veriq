"""OAuth resource-server validation; login and consent remain with the configured issuer."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import anyio
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from .ingestion import InputError, digest

READ_SCOPE = "veriq:read"
UPLOAD_SCOPE = "veriq:upload"


def https_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise InputError("hosted URLs must be absolute HTTPS URLs without credentials, query or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise InputError("invalid HTTPS port") from exc
    return value


@dataclass(frozen=True)
class HostedSettings:
    origin: str
    issuer: str
    jwks_url: str
    data_dir: Path
    upload_client_id: str = ""

    def __post_init__(self):
        for value in (self.origin, self.issuer, self.jwks_url):
            https_url(value)
        if urlsplit(self.origin).path or self.origin.endswith("/"):
            raise InputError("VERIQ_PUBLIC_ORIGIN must have no path or trailing slash")
        if len(self.upload_client_id) > 256 or any(c.isspace() for c in self.upload_client_id):
            raise InputError("VERIQ_UPLOAD_CLIENT_ID must be a public OAuth client ID")

    @property
    def resource(self):
        return self.origin + "/mcp"

    @classmethod
    def from_environment(cls):
        import os
        try:
            return cls(os.environ["VERIQ_PUBLIC_ORIGIN"], os.environ["VERIQ_OAUTH_ISSUER"],
                       os.environ["VERIQ_JWKS_URL"], Path(os.environ.get("VERIQ_DATA_DIR", "/data")),
                       os.environ.get("VERIQ_UPLOAD_CLIENT_ID", ""))
        except KeyError as exc:
            raise InputError("configure VERIQ_PUBLIC_ORIGIN, VERIQ_OAUTH_ISSUER and VERIQ_JWKS_URL before serving") from exc


class JWTVerifier:
    def __init__(self, settings):
        self.settings = settings
        self.keys = jwt.PyJWKClient(settings.jwks_url, timeout=5)

    async def verify_token(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 16_384:
            return None
        return await anyio.to_thread.run_sync(self._verify, token)

    def _verify(self, token):
        try:
            if jwt.get_unverified_header(token).get("alg") not in {"RS256", "ES256"}:
                return None
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=self.settings.resource,
                                issuer=self.settings.issuer, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            subject = claims["sub"]
            scope = claims.get("scope", "")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 512 or not isinstance(scope, str):
                return None
            client = claims.get("client_id", claims.get("azp", "veriq-oauth-client"))
            if not isinstance(client, str) or not client:
                return None
            return AccessToken(token=token, client_id=client, scopes=scope.split(), subject=subject,
                               expires_at=claims["exp"], resource=self.settings.resource, claims={"iss": claims["iss"]})
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return None


def principal(token=None):
    token = token or get_access_token()
    if token is None or token.subject is None or not (token.claims or {}).get("iss"):
        raise InputError("authenticated user identity required")
    return digest([token.claims["iss"], token.subject]).removeprefix("sha256:")
