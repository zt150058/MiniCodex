from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from threading import RLock
from typing import Protocol, runtime_checkable

from coding_agent.config import ApiMode, RunConfig, _normalize_chat_base_url


MAX_MODEL_ID_BYTES = 256
MAX_MODEL_IDS = 2_048
MODEL_CATALOG_UNAVAILABLE = "model_catalog_unavailable"


def _openai_client(**options: object) -> object:
    from openai import OpenAI

    return OpenAI(**options)


class ModelCatalogError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("model catalog error code must be non-empty")
        self.code = code
        super().__init__(code)


def require_model_id(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelCatalogError("invalid_model_id")
    if any(ord(character) <= 0x1F or ord(character) == 0x7F for character in value):
        raise ModelCatalogError("invalid_model_id")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ModelCatalogError("invalid_model_id") from None
    if len(encoded) > MAX_MODEL_ID_BYTES:
        raise ModelCatalogError("invalid_model_id")
    return value


class ModelCatalogStatus(StrEnum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ModelCatalogView:
    enabled: bool
    status: ModelCatalogStatus
    default_model_id: str
    model_ids: tuple[str, ...]
    error_code: str | None

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be bool")
        if type(self.status) is not ModelCatalogStatus:
            raise TypeError("status must be ModelCatalogStatus")
        default_model_id = require_model_id(self.default_model_id)
        if not isinstance(self.model_ids, tuple):
            raise TypeError("model_ids must be tuple")
        normalized = tuple(require_model_id(value) for value in self.model_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("model_ids must be unique")
        if default_model_id not in normalized:
            raise ValueError("default_model_id must be listed")
        valid_projection = (
            self.status is ModelCatalogStatus.DISABLED
            and self.enabled is False
            and self.error_code is None
            and normalized == (default_model_id,)
        ) or (
            self.status is ModelCatalogStatus.READY
            and self.enabled is True
            and self.error_code is None
        ) or (
            self.status
            in {ModelCatalogStatus.STALE, ModelCatalogStatus.UNAVAILABLE}
            and self.enabled is True
            and self.error_code == MODEL_CATALOG_UNAVAILABLE
        )
        if not valid_projection:
            raise ValueError("catalog view status is inconsistent")


@runtime_checkable
class ModelCatalog(Protocol):
    @property
    def default_model_id(self) -> str:
        raise NotImplementedError

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        raise NotImplementedError

    def resolve(self, requested_model_id: str | None) -> str:
        raise NotImplementedError


class DisabledModelCatalog:
    def __init__(self, default_model_id: str) -> None:
        self._default_model_id = require_model_id(default_model_id)
        self._view = ModelCatalogView(
            enabled=False,
            status=ModelCatalogStatus.DISABLED,
            default_model_id=self._default_model_id,
            model_ids=(self._default_model_id,),
            error_code=None,
        )

    @property
    def default_model_id(self) -> str:
        return self._default_model_id

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        if type(refresh) is not bool:
            raise TypeError("refresh must be bool")
        return self._view

    def resolve(self, requested_model_id: str | None) -> str:
        if requested_model_id is None:
            return self._default_model_id
        try:
            selected = require_model_id(requested_model_id)
        except ModelCatalogError:
            raise ModelCatalogError("model_not_available") from None
        if selected != self._default_model_id:
            raise ModelCatalogError("model_not_available")
        return selected


class ChatCompletionsModelCatalog:
    __slots__ = (
        "_client",
        "_default_model_id",
        "_last_good",
        "_lock",
        "_stale",
    )

    def __init__(
        self,
        *,
        default_model_id: str,
        api_key: str,
        base_url: str,
        sdk_client: object | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._default_model_id = require_model_id(default_model_id)
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        normalized_base_url = _normalize_chat_base_url(base_url)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        self._client = (
            _openai_client(
                api_key=api_key.strip(),
                base_url=normalized_base_url,
                max_retries=0,
                timeout=float(timeout_seconds),
            )
            if sdk_client is None
            else sdk_client
        )
        self._last_good: tuple[str, ...] | None = None
        self._stale = False
        self._lock = RLock()

    @property
    def default_model_id(self) -> str:
        return self._default_model_id

    def _view(
        self,
        status: ModelCatalogStatus,
        model_ids: tuple[str, ...],
    ) -> ModelCatalogView:
        return ModelCatalogView(
            enabled=True,
            status=status,
            default_model_id=self._default_model_id,
            model_ids=model_ids,
            error_code=(
                None
                if status is ModelCatalogStatus.READY
                else MODEL_CATALOG_UNAVAILABLE
            ),
        )

    def _discover(self) -> tuple[str, ...]:
        response = self._client.models.list()
        model_ids = {self._default_model_id}
        for item in response:
            try:
                model_id = require_model_id(getattr(item, "id", None))
            except ModelCatalogError:
                continue
            model_ids.add(model_id)
            if len(model_ids) > MAX_MODEL_IDS:
                raise ModelCatalogError(MODEL_CATALOG_UNAVAILABLE)
        return tuple(sorted(model_ids, key=lambda value: (value.casefold(), value)))

    def list_models(self, *, refresh: bool = False) -> ModelCatalogView:
        if type(refresh) is not bool:
            raise TypeError("refresh must be bool")
        with self._lock:
            if not refresh and self._last_good is not None:
                return self._view(
                    (
                        ModelCatalogStatus.STALE
                        if self._stale
                        else ModelCatalogStatus.READY
                    ),
                    self._last_good,
                )
            try:
                discovered = self._discover()
            except Exception:
                self._stale = self._last_good is not None
                if self._last_good is None:
                    return self._view(
                        ModelCatalogStatus.UNAVAILABLE,
                        (self._default_model_id,),
                    )
                return self._view(ModelCatalogStatus.STALE, self._last_good)
            self._last_good = discovered
            self._stale = False
            return self._view(ModelCatalogStatus.READY, discovered)

    def resolve(self, requested_model_id: str | None) -> str:
        if requested_model_id is None:
            return self._default_model_id
        try:
            selected = require_model_id(requested_model_id)
        except ModelCatalogError:
            raise ModelCatalogError("model_not_available") from None
        with self._lock:
            allowed = (
                (self._default_model_id,)
                if self._last_good is None
                else self._last_good
            )
            if selected not in allowed:
                raise ModelCatalogError("model_not_available")
        return selected


def create_model_catalog(config: RunConfig) -> ModelCatalog:
    if not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig")
    if config.api_mode is ApiMode.RESPONSES:
        return DisabledModelCatalog(config.model)
    if config.base_url is None:
        raise ValueError("chat-completions base_url is missing")
    return ChatCompletionsModelCatalog(
        default_model_id=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
    )
