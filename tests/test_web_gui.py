from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
import tomllib

from coding_agent.web import create_web_app
from coding_agent.web_auth import WebAccessPolicy
from tests.web_support import RecordingController, request


TOKEN = "fixed-test-token"
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IDS = {
    "session-sidebar",
    "new-session-button",
    "session-list",
    "skill-list",
    "skill-toggle",
    "skill-panel",
    "skill-summary",
    "conversation-title",
    "run-status",
    "run-phase",
    "run-elapsed",
    "cancel-run-button",
    "conversation-log",
    "message-composer",
    "message-input",
    "send-message-button",
    "connection-status",
    "coding-agent-bootstrap",
}


class GuiMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.tags: list[str] = []
        self.attributes: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        self.tags.append(tag)
        self.attributes.append((tag, attributes))
        if "id" in attributes and attributes["id"] is not None:
            self.ids.append(attributes["id"])


def gui_source(name: str) -> str:
    return files("coding_agent").joinpath("web_static", name).read_text(
        encoding="utf-8"
    )


def make_app(*, token: str = TOKEN, gui_root: Path | None = None):
    return create_web_app(
        controller=RecordingController(),
        access_policy=WebAccessPolicy(token=token, port=43123),
        gui_root=gui_root,
    )


def document_headers(**overrides: str) -> dict[str, str]:
    headers = {"Origin": "http://127.0.0.1:43123"}
    headers.update(overrides)
    return headers


def test_packaged_gui_resources_are_discoverable() -> None:
    root = files("coding_agent").joinpath("web_static")

    assert root.joinpath("index.html").is_file()
    assert root.joinpath("app.js").is_file()
    assert root.joinpath("styles.css").is_file()


def test_package_metadata_declares_gui_assets_and_web_entry() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"]["coding-agent-web"] == (
        "coding_agent.web_cli:entrypoint"
    )
    package_data = metadata["tool"]["setuptools"]["package-data"]["coding_agent"]
    assert package_data == [
        "web_static/*.html",
        "web_static/*.css",
        "web_static/*.js",
    ]


def test_document_bootstrap_is_uncached_hardened_and_replaces_token_once() -> None:
    response = asyncio.run(
        request(make_app(), "GET", "/", headers=document_headers())
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    policy = response.headers["content-security-policy"]
    for directive in (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ):
        assert directive in policy
    assert response.text.count(TOKEN) == 1
    assert "__CODING_AGENT_ACCESS_TOKEN__" not in response.text


def test_document_bootstrap_html_escapes_the_access_token() -> None:
    token = 'token&quot;<tag>"'
    response = asyncio.run(
        request(
            make_app(token=token),
            "GET",
            "/",
            headers=document_headers(),
        )
    )

    assert response.status_code == 200
    assert token not in response.text
    assert "token&amp;quot;&lt;tag&gt;&quot;" in response.text


def test_document_rejects_invalid_host_and_origin_without_bearer() -> None:
    invalid_host = asyncio.run(
        request(
            make_app(),
            "GET",
            "/",
            headers=document_headers(Host="attacker.invalid"),
        )
    )
    invalid_origin = asyncio.run(
        request(
            make_app(),
            "GET",
            "/",
            headers=document_headers(Origin="http://attacker.invalid"),
        )
    )

    assert invalid_host.status_code == 403
    assert invalid_host.json() == {"error": {"code": "request_forbidden"}}
    assert invalid_origin.status_code == 403
    assert invalid_origin.json() == {"error": {"code": "request_forbidden"}}


def test_static_resources_have_exact_media_and_security_headers() -> None:
    app = make_app()

    script = asyncio.run(
        request(app, "GET", "/app.js", headers=document_headers())
    )
    styles = asyncio.run(
        request(app, "GET", "/styles.css", headers=document_headers())
    )

    assert script.status_code == 200
    assert script.headers["content-type"] == "text/javascript; charset=utf-8"
    assert styles.status_code == 200
    assert styles.headers["content-type"] == "text/css; charset=utf-8"
    for response in (script, styles):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert TOKEN not in response.text


def test_bootstrap_marker_corruption_returns_fixed_internal_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text(
        "<html>missing marker</html>",
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "styles.css").write_text("html {}", encoding="utf-8")

    response = asyncio.run(
        request(
            make_app(gui_root=tmp_path),
            "GET",
            "/",
            headers=document_headers(),
        )
    )

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_server_error"}}


def test_gui_layout_has_unique_semantic_landmarks_and_controls() -> None:
    parser = GuiMarkupParser()
    parser.feed(gui_source("index.html"))

    assert REQUIRED_IDS <= set(parser.ids)
    assert all(parser.ids.count(identifier) == 1 for identifier in REQUIRED_IDS)
    for tag in ("nav", "main", "header", "ol", "form"):
        assert tag in parser.tags
    buttons = [attrs for tag, attrs in parser.attributes if tag == "button"]
    assert buttons
    assert all(button.get("type") in {"button", "submit"} for button in buttons)
    assert any(
        attrs.get("aria-live") == "polite"
        for _tag, attrs in parser.attributes
    )
    assert not any(
        name.lower().startswith("on")
        for _tag, attrs in parser.attributes
        for name in attrs
    )


def test_gui_accessibility_labels_every_interactive_form_control() -> None:
    parser = GuiMarkupParser()
    parser.feed(gui_source("index.html"))
    label_targets = {
        attrs["for"]
        for tag, attrs in parser.attributes
        if tag == "label" and attrs.get("for")
    }

    controls = [
        attrs
        for tag, attrs in parser.attributes
        if tag in {"button", "input", "select", "textarea"}
    ]
    assert controls
    for control in controls:
        assert (
            bool(control.get("aria-label"))
            or bool(control.get("aria-labelledby"))
            or control.get("id") in label_targets
            or bool(control.get("title"))
        )


def test_skill_panel_is_compact_collapsed_and_accessibly_expandable() -> None:
    parser = GuiMarkupParser()
    parser.feed(gui_source("index.html"))
    attributes = {
        attrs.get("id"): attrs
        for _tag, attrs in parser.attributes
        if attrs.get("id")
    }

    toggle = attributes["skill-toggle"]
    panel = attributes["skill-panel"]
    assert toggle["type"] == "button"
    assert toggle["aria-expanded"] == "false"
    assert toggle["aria-controls"] == "skill-panel"
    assert "hidden" in panel


def test_gui_palette_and_wide_central_layout_match_approved_design() -> None:
    css = gui_source("styles.css")

    for custom_property in (
        "--color-background:",
        "--color-surface:",
        "--color-ink:",
        "--color-accent:",
        "--color-success:",
        "--color-running:",
        "--color-failure:",
        "--color-border:",
        "--shadow-soft:",
    ):
        assert custom_property in css
    assert "grid-template-columns: 260px minmax(0, 1fr)" in css
    assert "position: sticky" in css
    assert "#000" not in css.lower()
    assert "background: black" not in css.lower()
    assert "http://" not in css.lower()
    assert "https://" not in css.lower()


def test_gui_responsive_drawer_focus_and_reduced_motion_are_explicit() -> None:
    css = gui_source("styles.css")

    assert "@media (max-width: 800px)" in css
    assert "transform: translateX(-100%)" in css
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
