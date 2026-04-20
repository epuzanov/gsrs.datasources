from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from .base import Base


class Db(Base):
    def __init__(self, resourceType: str, **kwargs: Any) -> None:
        super().__init__(resourceType=resourceType, **kwargs)
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def get(
        self,
        id: str,
        version: str | None = None,
        raw: bool = False,
        template: Mapping[str, Any] | str | None = None,
        *,
        view: str | None = None,
    ) -> Any:
        raise NotImplementedError("Db datasource is not implemented yet.")

    def search(
        self,
        query: str | None = None,
        *,
        page_size: int = 50,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> list[str]:
        raise NotImplementedError("Db datasource is not implemented yet.")

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
        raise NotImplementedError("Db datasource is not implemented yet.")

    def save(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> Any:
        raise NotImplementedError("Db datasource is not implemented yet.")

    def validate(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> Any:
        raise NotImplementedError("Db datasource is not implemented yet.")
