from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import Any

from .exceptions import ResourceTypeError

RESOURCE_MAP: dict[str, dict[str, str]] = {
    "Substance": {
        "path": "substances",
        "id_field": "uuid",
        "model_name": "Substance",
    },
    "Product": {
        "path": "products",
        "id_field": "uuid",
        "model_name": "Product",
    },
}

class Base(ABC):
    RESOURCE_MAP = RESOURCE_MAP

    def __init__(self, resourceType: str, **kwargs: Any) -> None:
        self._logger = kwargs.get("logger", None)
        self._dsname = kwargs.get("dsName", "COMMON")
        self._codeSystem = kwargs.get("codeSystem", "Unknown")
        self._resourceType = resourceType
        self._resource = self.get_resource_config(resourceType)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @classmethod
    def get_resource_config(cls, resourceType: str) -> dict[str, str]:
        try:
            return cls.RESOURCE_MAP[resourceType]
        except KeyError as exc:
            supported = ", ".join(sorted(cls.RESOURCE_MAP))
            raise ResourceTypeError(
                f"Unsupported resourceType {resourceType!r}. Supported values: {supported}."
            ) from exc

    def extend(self, obj: Any) -> Any:
        return obj

    @property
    def resourceType(self) -> str:
        return self._resourceType

    @property
    def resource(self) -> dict[str, str]:
        return self._resource

    @abstractmethod
    def close(self) -> None:
        """Release any datasource resources."""

    @abstractmethod
    def get(
        self,
        id: str,
        version: str | None = None,
        raw: bool = False,
        template: Mapping[str, Any] | str | None = None,
        *,
        view: str | None = None,
    ) -> Any:
        """Fetch one record from the datasource."""

    @abstractmethod
    def search(
        self,
        query: str | None = None,
        *,
        page_size: int = 50,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> list[str]:
        """Return matching record identifiers."""

    @abstractmethod
    def iterate(
        self,
        query: str | None = None,
        *,
        raw: bool = False,
        page_size: int = 50,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> Iterator[Any]:
        """Yield matching records lazily."""

    @abstractmethod
    def save(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> Any:
        """Create or update a record in the datasource."""

    @abstractmethod
    def validate(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> Any:
        """Validate a record payload without saving it."""
