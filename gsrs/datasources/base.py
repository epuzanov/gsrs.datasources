from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

from pydantic import BaseModel

__all__ = ["Base"]


class Base(ABC):
    """Common datasource contract.

    ``resourceType`` is the model class that API payloads are cast to. When it
    is ``None`` the datasource is untyped: every payload is returned as raw
    JSON and requests are resolved against ``base_url`` without an entity
    segment. When a class is given, payloads are cast to that class.
    """

    def __init__(
            self,
            resource_type: type | None = None,
            resource_path: str | None = None,
            id_field: str | None = None,
            logger: Any | None = None,
            **kwargs: Any,
    ) -> None:
        # ``resourceType`` is the historical camelCase alias for
        # ``resource_type`` and is what the documentation uses.
        if resource_type is None and "resourceType" in kwargs:
            resource_type = kwargs.pop("resourceType")
        self.logger = logger
        self.resource_type = resource_type
        if resource_path is None and callable(getattr(resource_type, "_resource_path", None)):
            resource_path = resource_type._resource_path()
        # An empty path means raw mode: requests resolve against ``base_url``.
        self.resource_path = (resource_path or "").strip("/")
        if id_field is None and callable(getattr(resource_type, "_id_field", None)):
            id_field = resource_type._id_field()
        self.id_field = id_field

    def __del__(self) -> None:
        # Interpreter shutdown may already have cleared what ``close`` needs.
        with suppress(Exception):
            self.close()

    def _cast_payload(self, payload: Any) -> Any:
        """Cast ``payload`` to the configured model class, or pass it through."""
        if self.resource_type is None or payload is None:
            return payload
        return self.resource_type.model_validate(payload)

    @abstractmethod
    def close(self) -> None:
        """Release any datasource resources."""

    @abstractmethod
    def get(
        self,
        id: str,
        version: str | None = None,
    ) -> Any:
        """Fetch one record, cast to ``resource_type`` unless it is ``None``."""

    @abstractmethod
    def search(
        self,
        query: str | None = None,
    ) -> list[str]:
        """Return matching record identifiers."""

    @abstractmethod
    def iterate(
        self,
        query: str | None = None,
    ) -> Iterator[Any]:
        """Yield matching records, cast to ``resource_type`` unless it is ``None``."""

    @abstractmethod
    def save(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> Any:
        """Create or update a record, cast to ``resource_type`` unless it is ``None``."""

    @abstractmethod
    def validate(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> Any:
        """Validate a record payload without saving it."""

    @abstractmethod
    def approve(
        self,
        id: str,
    ) -> Any:
        """Approve the record, cast to ``resource_type`` unless it is ``None``."""

