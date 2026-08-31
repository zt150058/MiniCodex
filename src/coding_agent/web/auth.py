from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field


class WebAuthorizationError(RuntimeError):
    """Stable, non-sensitive request authorization failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def default_token_factory() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class WebAccessPolicy:
    token: str = field(repr=False)
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.token, str):
            raise TypeError("token must be a string")
        if not self.token.strip():
            raise ValueError("token must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise TypeError("port must be an integer")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    @classmethod
    def generate(
        cls,
        port: int,
        *,
        token_factory: Callable[[], str] = default_token_factory,
    ) -> WebAccessPolicy:
        if not callable(token_factory):
            raise TypeError("token_factory must be callable")
        return cls(token=token_factory(), port=port)

    def authorize(
        self,
        raw_headers: tuple[tuple[bytes, bytes], ...],
        *,
        require_bearer: bool,
    ) -> None:
        hosts = _header_values(raw_headers, b"host")
        if len(hosts) != 1:
            raise WebAuthorizationError("request_forbidden")

        expected_hosts = {
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
        }
        host = _decode_ascii(hosts[0], code="request_forbidden")
        if host not in expected_hosts:
            raise WebAuthorizationError("request_forbidden")

        origins = _header_values(raw_headers, b"origin")
        if len(origins) > 1:
            raise WebAuthorizationError("request_forbidden")
        if origins:
            origin = _decode_ascii(origins[0], code="request_forbidden")
            if origin != f"http://{host}":
                raise WebAuthorizationError("request_forbidden")

        if not require_bearer:
            return

        authorization = _header_values(raw_headers, b"authorization")
        if len(authorization) != 1:
            raise WebAuthorizationError("unauthorized")
        value = _decode_ascii(authorization[0], code="unauthorized")
        prefix = "Bearer "
        if not value.startswith(prefix):
            raise WebAuthorizationError("unauthorized")
        provided_token = value[len(prefix) :]
        if not provided_token or not secrets.compare_digest(provided_token, self.token):
            raise WebAuthorizationError("unauthorized")


def _header_values(
    raw_headers: tuple[tuple[bytes, bytes], ...], name: bytes
) -> tuple[bytes, ...]:
    return tuple(value for key, value in raw_headers if key.lower() == name)


def _decode_ascii(value: bytes, *, code: str) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as error:
        raise WebAuthorizationError(code) from error
