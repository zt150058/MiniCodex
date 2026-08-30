from __future__ import annotations

import pytest


TOKEN = "fixed-test-token"


def raw_headers(*pairs: tuple[str, str]) -> tuple[tuple[bytes, bytes], ...]:
    return tuple(
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in pairs
    )


def valid_headers(
    *, origin: str | None = "http://127.0.0.1:43123"
) -> tuple[tuple[bytes, bytes], ...]:
    pairs = [
        ("host", "127.0.0.1:43123"),
        ("authorization", f"Bearer {TOKEN}"),
    ]
    if origin is not None:
        pairs.append(("origin", origin))
    return raw_headers(*pairs)


def test_policy_generates_one_hidden_process_token() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    calls: list[None] = []
    policy = WebAccessPolicy.generate(
        43123,
        token_factory=lambda: calls.append(None) or TOKEN,
    )

    assert calls == [None]
    assert policy.port == 43123
    assert TOKEN not in repr(policy)


@pytest.mark.parametrize("port", [True, 0, -1, 65536, 1.5, "80"])
def test_policy_rejects_invalid_port(port: object) -> None:
    from coding_agent.web_auth import WebAccessPolicy

    with pytest.raises((TypeError, ValueError)):
        WebAccessPolicy(token=TOKEN, port=port)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", [None, "", "   ", 123])
def test_policy_rejects_invalid_token(token: object) -> None:
    from coding_agent.web_auth import WebAccessPolicy

    with pytest.raises((TypeError, ValueError)):
        WebAccessPolicy(token=token, port=43123)  # type: ignore[arg-type]


def test_policy_rejects_non_callable_token_factory() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    with pytest.raises(TypeError, match="token_factory must be callable"):
        WebAccessPolicy.generate(43123, token_factory=TOKEN)  # type: ignore[arg-type]


def test_authorize_accepts_exact_ipv4_and_localhost_origins() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    policy = WebAccessPolicy(token=TOKEN, port=43123)
    policy.authorize(valid_headers(), require_bearer=True)
    policy.authorize(
        raw_headers(
            ("host", "localhost:43123"),
            ("origin", "http://localhost:43123"),
            ("authorization", f"Bearer {TOKEN}"),
        ),
        require_bearer=True,
    )
    policy.authorize(valid_headers(origin=None), require_bearer=True)


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        (raw_headers(("authorization", f"Bearer {TOKEN}")), "request_forbidden"),
        (
            raw_headers(
                ("host", "evil.example:43123"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1.evil:43123"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1:43124"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
        (raw_headers(("host", "127.0.0.1:43123")), "unauthorized"),
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("authorization", "Basic abc"),
            ),
            "unauthorized",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("authorization", "Bearer wrong"),
            ),
            "unauthorized",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("origin", "https://127.0.0.1:43123"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
    ],
)
def test_authorize_rejects_invalid_requests(
    headers: tuple[tuple[bytes, bytes], ...], code: str
) -> None:
    from coding_agent.web_auth import WebAccessPolicy, WebAuthorizationError

    with pytest.raises(WebAuthorizationError) as caught:
        WebAccessPolicy(token=TOKEN, port=43123).authorize(
            headers, require_bearer=True
        )
    assert caught.value.code == code
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("host", "127.0.0.1:43123"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("origin", "http://127.0.0.1:43123"),
                ("origin", "http://127.0.0.1:43123"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "request_forbidden",
        ),
        (
            raw_headers(
                ("host", "127.0.0.1:43123"),
                ("authorization", f"Bearer {TOKEN}"),
                ("authorization", f"Bearer {TOKEN}"),
            ),
            "unauthorized",
        ),
    ],
)
def test_authorize_rejects_duplicate_security_headers(
    headers: tuple[tuple[bytes, bytes], ...], code: str
) -> None:
    from coding_agent.web_auth import WebAccessPolicy, WebAuthorizationError

    with pytest.raises(WebAuthorizationError) as caught:
        WebAccessPolicy(token=TOKEN, port=43123).authorize(
            headers, require_bearer=True
        )
    assert caught.value.code == code


def test_document_authorization_does_not_parse_authorization_header() -> None:
    from coding_agent.web_auth import WebAccessPolicy

    WebAccessPolicy(token=TOKEN, port=43123).authorize(
        raw_headers(
            ("host", "127.0.0.1:43123"),
            ("origin", "http://127.0.0.1:43123"),
            ("authorization", "Basic ignored"),
            ("authorization", "Bearer also-ignored"),
        ),
        require_bearer=False,
    )


@pytest.mark.parametrize(
    "headers",
    [
        (),
        raw_headers(("host", "evil.example:43123")),
        raw_headers(
            ("host", "127.0.0.1:43123"),
            ("origin", "http://localhost:43123"),
        ),
    ],
)
def test_document_authorization_still_enforces_host_and_origin(
    headers: tuple[tuple[bytes, bytes], ...]
) -> None:
    from coding_agent.web_auth import WebAccessPolicy, WebAuthorizationError

    with pytest.raises(WebAuthorizationError) as caught:
        WebAccessPolicy(token=TOKEN, port=43123).authorize(
            headers, require_bearer=False
        )
    assert caught.value.code == "request_forbidden"
