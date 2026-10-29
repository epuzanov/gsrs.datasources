"""Placeholder database datasource.

The class reserves the :class:`Base` contract for a future SQL implementation;
no method here is implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from .base import Base

__all__ = ["Db"]

NOT_IMPLEMENTED_MESSAGE = "Db datasource is not implemented yet."


class Db(Base):
    """Stub datasource for a database backend.

    Every operation raises :class:`NotImplementedError`; the class exists so the
    datasource contract has a documented placeholder.
    """

    def __init__(self, resource_type: type | None = None, **kwargs: Any) -> None:
        super().__init__(resource_type=resource_type, **kwargs)
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def get(
        self,
        id: str,
        version: str | None = None,
    ) -> Any:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)

    def search(
        self,
        query: str | None = None,
    ) -> list[str]:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)

    def iterate(
        self,
        query: str | None = None,
    ) -> Iterator[Any]:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)

    def save(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> Any:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)

    def validate(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> Any:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)

    def approve(
        self,
        id: str,
    ) -> Any:
        raise NotImplementedError(NOT_IMPLEMENTED_MESSAGE)
