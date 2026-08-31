from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

import pytest

from coding_agent.application.config import ApiMode, RunConfig
from coding_agent.providers.model_catalog import (
    ChatCompletionsModelCatalog,
    DisabledModelCatalog,
    MODEL_CATALOG_UNAVAILABLE,
    ModelCatalog,
    ModelCatalogError,
    ModelCatalogStatus,
    ModelCatalogView,
    create_model_catalog,
    require_model_id,
)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        7,
        "",
        " model",
        "model ",
        "model\nname",
        "\ud800",
        "é" * 129,
    ],
)
def test_model_id_rejects_invalid_or_oversized_values(value: object) -> None:
    with pytest.raises(ModelCatalogError, match="^invalid_model_id$"):
        require_model_id(value)


def test_model_id_preserves_exact_valid_text_at_utf8_limit() -> None:
    model_id = "é" * 128

    assert require_model_id(model_id) == model_id


def test_catalog_view_requires_default_in_unique_valid_model_ids() -> None:
    with pytest.raises(ValueError, match="default_model_id must be listed"):
        ModelCatalogView(
            enabled=True,
            status=ModelCatalogStatus.READY,
            default_model_id="default-model",
            model_ids=("other-model",),
            error_code=None,
        )

    with pytest.raises(ValueError, match="model_ids must be unique"):
        ModelCatalogView(
            enabled=True,
            status=ModelCatalogStatus.READY,
            default_model_id="default-model",
            model_ids=("default-model", "default-model"),
            error_code=None,
        )


def test_disabled_catalog_exposes_and_resolves_only_configured_default() -> None:
    catalog = DisabledModelCatalog("default-model")

    assert catalog.default_model_id == "default-model"
    assert catalog.list_models() == ModelCatalogView(
        enabled=False,
        status=ModelCatalogStatus.DISABLED,
        default_model_id="default-model",
        model_ids=("default-model",),
        error_code=None,
    )
    assert catalog.list_models(refresh=True) == catalog.list_models()
    assert catalog.resolve(None) == "default-model"
    assert catalog.resolve("default-model") == "default-model"

    with pytest.raises(ModelCatalogError, match="^model_not_available$"):
        catalog.resolve("other-model")


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "enabled": True,
            "status": ModelCatalogStatus.DISABLED,
            "error_code": None,
        },
        {
            "enabled": False,
            "status": ModelCatalogStatus.READY,
            "error_code": None,
        },
        {
            "enabled": True,
            "status": ModelCatalogStatus.STALE,
            "error_code": None,
        },
        {
            "enabled": True,
            "status": ModelCatalogStatus.UNAVAILABLE,
            "error_code": "provider-secret-message",
        },
    ],
)
def test_catalog_view_rejects_inconsistent_status_projection(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="catalog view status is inconsistent"):
        ModelCatalogView(
            default_model_id="default-model",
            model_ids=("default-model",),
            **kwargs,
        )


@dataclass(frozen=True, slots=True)
class _FakeProviderModel:
    id: object
    created: int = 1
    object: str = "model"
    owned_by: str = "test-owner"


class _FakeModelsResource:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = deque(outcomes)
        self.calls = 0

    def list(self) -> object:
        self.calls += 1
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@dataclass(slots=True)
class _FakeSdkClient:
    models: object


def _chat_catalog(
    resource: object,
    *,
    api_key: str = "catalog-test-key",
    base_url: str = "https://provider.example/v1/",
) -> ChatCompletionsModelCatalog:
    return ChatCompletionsModelCatalog(
        default_model_id="default-model",
        api_key=api_key,
        base_url=base_url,
        sdk_client=_FakeSdkClient(models=resource),
    )


def test_chat_catalog_rejects_unvalidated_base_url_before_sdk_use() -> None:
    with pytest.raises(ValueError, match="absolute HTTPS URL"):
        ChatCompletionsModelCatalog(
            default_model_id="default-model",
            api_key="catalog-test-key",
            base_url="http://provider.example/v1/",
            sdk_client=_FakeSdkClient(models=_FakeModelsResource([])),
        )


def test_chat_catalog_returns_every_valid_unique_id_in_stable_order() -> None:
    resource = _FakeModelsResource(
        [
            _FakeProviderModel("z-model"),
            _FakeProviderModel("A-model"),
            _FakeProviderModel("z-model"),
            _FakeProviderModel(" invalid"),
            _FakeProviderModel(None),
        ]
    )
    catalog = _chat_catalog(resource)

    view = catalog.list_models()

    assert view == ModelCatalogView(
        enabled=True,
        status=ModelCatalogStatus.READY,
        default_model_id="default-model",
        model_ids=("A-model", "default-model", "z-model"),
        error_code=None,
    )
    assert resource.calls == 1
    assert catalog.list_models() == view
    assert resource.calls == 1
    assert catalog.resolve("A-model") == "A-model"
    with pytest.raises(ModelCatalogError, match="^model_not_available$"):
        catalog.resolve("missing-model")


def test_explicit_refresh_replaces_authorized_snapshot() -> None:
    resource = _FakeModelsResource(
        [_FakeProviderModel("old-model")],
        [_FakeProviderModel("new-model")],
    )
    catalog = _chat_catalog(resource)

    assert "old-model" in catalog.list_models().model_ids
    refreshed = catalog.list_models(refresh=True)

    assert refreshed.status is ModelCatalogStatus.READY
    assert refreshed.model_ids == ("default-model", "new-model")
    assert resource.calls == 2
    with pytest.raises(ModelCatalogError, match="^model_not_available$"):
        catalog.resolve("old-model")
    assert catalog.resolve("new-model") == "new-model"


def test_failed_initial_discovery_returns_only_default_without_provider_text() -> None:
    secret = "provider-secret-response"
    resource = _FakeModelsResource(RuntimeError(secret))
    catalog = _chat_catalog(
        resource,
        api_key="secret-catalog-key",
        base_url="https://secret-provider.example/v1/",
    )

    view = catalog.list_models()

    assert view == ModelCatalogView(
        enabled=True,
        status=ModelCatalogStatus.UNAVAILABLE,
        default_model_id="default-model",
        model_ids=("default-model",),
        error_code=MODEL_CATALOG_UNAVAILABLE,
    )
    projected = repr(view) + repr(catalog)
    assert secret not in projected
    assert "secret-catalog-key" not in projected
    assert "secret-provider.example" not in projected


def test_failed_refresh_preserves_last_good_snapshot_as_stale() -> None:
    resource = _FakeModelsResource(
        [_FakeProviderModel("available-model")],
        RuntimeError("do-not-project-this"),
    )
    catalog = _chat_catalog(resource)
    ready = catalog.list_models()

    stale = catalog.list_models(refresh=True)

    assert stale == ModelCatalogView(
        enabled=True,
        status=ModelCatalogStatus.STALE,
        default_model_id="default-model",
        model_ids=ready.model_ids,
        error_code=MODEL_CATALOG_UNAVAILABLE,
    )
    assert catalog.list_models() == stale
    assert resource.calls == 2
    assert catalog.resolve("available-model") == "available-model"


def test_catalog_limit_is_complete_or_fail_instead_of_partial() -> None:
    within_limit = [
        _FakeProviderModel(f"model-{index:04d}")
        for index in range(2_047)
    ]
    above_limit_after_default = [
        _FakeProviderModel(f"overflow-{index:04d}")
        for index in range(2_048)
    ]
    resource = _FakeModelsResource(within_limit, above_limit_after_default)
    catalog = _chat_catalog(resource)

    ready = catalog.list_models()
    stale = catalog.list_models(refresh=True)

    assert ready.status is ModelCatalogStatus.READY
    assert len(ready.model_ids) == 2_048
    assert stale.status is ModelCatalogStatus.STALE
    assert stale.model_ids == ready.model_ids
    assert not any(value.startswith("overflow-") for value in stale.model_ids)


def test_iteration_failure_discards_partial_snapshot() -> None:
    def broken_response():
        yield _FakeProviderModel("partial-model")
        raise RuntimeError("broken pagination")

    catalog = _chat_catalog(_FakeModelsResource(broken_response()))

    view = catalog.list_models()

    assert view.status is ModelCatalogStatus.UNAVAILABLE
    assert view.model_ids == ("default-model",)
    with pytest.raises(ModelCatalogError, match="^model_not_available$"):
        catalog.resolve("partial-model")


def test_catalog_does_not_swallow_base_exception() -> None:
    catalog = _chat_catalog(_FakeModelsResource(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        catalog.list_models()


def test_concurrent_initial_reads_share_one_complete_discovery() -> None:
    entered = Event()
    release = Event()

    class BlockingModelsResource:
        def __init__(self) -> None:
            self.calls = 0

        def list(self) -> list[_FakeProviderModel]:
            self.calls += 1
            entered.set()
            assert release.wait(timeout=2.0)
            return [_FakeProviderModel("shared-model")]

    resource = BlockingModelsResource()
    catalog = _chat_catalog(resource)
    views: list[ModelCatalogView] = []

    first = Thread(target=lambda: views.append(catalog.list_models()))
    second = Thread(target=lambda: views.append(catalog.list_models()))
    first.start()
    assert entered.wait(timeout=1.0)
    second.start()
    release.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert first.is_alive() is False
    assert second.is_alive() is False
    assert resource.calls == 1
    assert views == [
        ModelCatalogView(
            enabled=True,
            status=ModelCatalogStatus.READY,
            default_model_id="default-model",
            model_ids=("default-model", "shared-model"),
            error_code=None,
        ),
        ModelCatalogView(
            enabled=True,
            status=ModelCatalogStatus.READY,
            default_model_id="default-model",
            model_ids=("default-model", "shared-model"),
            error_code=None,
        ),
    ]


def test_catalog_factory_keeps_responses_disabled_without_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_sdk(**_kwargs: object) -> object:
        raise AssertionError("Responses catalog must not construct an SDK client")

    monkeypatch.setattr("coding_agent.providers.model_catalog._openai_client", forbidden_sdk)
    config = RunConfig(
        task="test",
        workspace=tmp_path,
        model="responses-model",
        api_key="responses-test-key",
        api_mode=ApiMode.RESPONSES,
    )

    catalog = create_model_catalog(config)

    assert isinstance(catalog, ModelCatalog)
    assert catalog.list_models().status is ModelCatalogStatus.DISABLED


def test_chat_catalog_factory_constructs_sdk_without_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    resource = _FakeModelsResource([_FakeProviderModel("provider-model")])

    def fake_openai(**kwargs: object) -> _FakeSdkClient:
        observed.update(kwargs)
        return _FakeSdkClient(models=resource)

    monkeypatch.setattr("coding_agent.providers.model_catalog._openai_client", fake_openai)
    config = RunConfig(
        task="test",
        workspace=tmp_path,
        model="chat-model",
        api_key="chat-test-key",
        api_mode=ApiMode.CHAT_COMPLETIONS,
        base_url="https://provider.example/v1",
    )

    catalog = create_model_catalog(config)

    assert isinstance(catalog, ModelCatalog)
    assert observed == {
        "api_key": "chat-test-key",
        "base_url": "https://provider.example/v1/",
        "max_retries": 0,
        "timeout": 10.0,
    }
    assert resource.calls == 0
    assert catalog.list_models().model_ids == ("chat-model", "provider-model")
    assert resource.calls == 1
