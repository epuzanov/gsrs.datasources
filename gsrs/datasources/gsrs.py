from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from gsrs.exceptions import ApiResponseError
from gsrs.responses import ValidationResponse, WhoAmIResponse

from .http import Http


class Gsrs(Http):
    """Datasource for the GSRS API.

    Endpoint suffixes for the GSRS-specific operations are kept as class
    attributes so subclasses and tests can override them.
    """

    APPROVE_PATH = "@approve"
    VALIDATE_PATH = "@validate"
    SEARCH_PATH = "search"
    WHOAMI_PATH = "whoami"

    def get(
        self,
        id: str,
        version: str | None = None,
    ) -> Any:
        params = {"view": "full"}
        url = self._resource_url(str(id))
        if version is not None:
            url = f"{url}/v/{str(version)}"
        payload = self._request_json("GET", url, params=params)
        return self._cast_payload(payload)

    def search(
        self,
        query: str | None = None,
    ) -> list[str]:
        params = {"view": "key"}
        identifiers: list[str] = []
        for item in self._query(
            query=query,
            page_size=50,
            params=params,
        ):
            identifier = item.get("idString")
            if identifier is None:
                raise ValueError(
                    f"Search result for {self.resource_type!r} did not include 'idString'."
                )
            identifiers.append(str(identifier))
        return identifiers

    def iterate(
        self,
        query: str | None = None,
    ) -> Iterator[Any]:
        params = {"view": "full"}
        for item in self._query(
            query=query,
            page_size=10,
            params=params,
        ):
            yield self._cast_payload(item)

    def save(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> Any:
        method = "POST"
        path = self.resource_path
        identifier = obj.get(str(self.id_field)) if isinstance(obj, dict) else getattr(obj, str(self.id_field), None)
        if identifier is not None:
            try:
                version = int(self._request_json("GET", self._resource_url(identifier, "version")))
                if isinstance(obj, dict):
                    if obj.get("version", 1) < version:
                        obj["version"] = version
                else:
                    if getattr(obj, "version", 1) < version:
                        setattr(obj, "version", version)
                method = "PUT"
                path = self._resource_url(identifier)
            except ApiResponseError as e:
                if e.status_code != 404:
                    raise
            except Exception:
                pass
        saved = self._request_json(
            method,
            str(path),
            data=obj,
        )
        return self._cast_payload(saved)

    def validate(
        self,
        obj: BaseModel | dict[str, Any],
    ) -> ValidationResponse:
        """Validate ``obj`` against GSRS.

        The payload is always POSTed: ``@validate`` is a read-only operation and
        GSRS does not accept a method override on it.
        """
        return ValidationResponse.model_validate(
            self._request_json(
                "POST",
                self._resource_url(self.VALIDATE_PATH),
                data=obj,
            )
        )

    def approve(
        self,
        id: str,
    ) -> Any:
        payload = self._request_json(
            "GET",
            self._resource_url(str(id), self.APPROVE_PATH),
        )
        return self._cast_payload(payload)

    def whoami(self) -> WhoAmIResponse:
        return WhoAmIResponse.model_validate(self._request_json("GET", self.WHOAMI_PATH))

    def _query(
        self,
        *,
        query: str | None = None,
        page_size: int = 50,
        params: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        # Copy so the caller's dict is never mutated by pagination.
        request_params = dict(params or {})
        if query:
            request_params["q"] = query
        yield from self._paginate(
            self._resource_url(self.SEARCH_PATH),
            params=request_params,
            page_size=page_size,
        )

