from __future__ import annotations

from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import Any
from urllib.parse import quote

from .base import Base
from .http import Http
from .validation import ValidationResponse


class Gsrs(Http):
    VIEW_FULL = "full"
    VIEW_COMPACT = "compact"
    VIEW_KEY = "key"
    VALIDATE_PATH = "@validate"

    def get(
        self,
        id: str,
        version: str | None = None,
        raw: bool = False,
        template: Mapping[str, Any] | str | None = None,
        *,
        view: str | None = None,
    ) -> Any:
        params = self._build_query_params(
            template=template,
            view=view,
        )
        if version is not None:
            params["version"] = version
        payload = self._request_json("GET", f"{self.resource['path']}/{quote(str(id))}", params=params)
        return self.extend(self._hydrate(payload, raw=raw))

    def search(
        self,
        query: str | None = None,
        *,
        page_size: int = 50,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> list[str]:
        identifiers: list[str] = []
        for item in self._query(
            self.resource["path"],
            query=query,
            page_size=page_size,
            params=params,
            template=template,
            view=view,
        ):
            identifier = item.get(self.resource["id_field"])
            if identifier is None:
                raise ValueError(
                    f"Search result for {self.resourceType!r} did not include {self.resource['id_field']!r}."
                )
            identifiers.append(str(identifier))
        return identifiers

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
        for item in self._query(
            self.resource["path"],
            query=query,
            page_size=page_size,
            params=params,
            template=template,
            view=view,
        ):
            yield self.extend(self._hydrate(item, raw=raw))

    def save(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> Any:
        inferred_resource_type = self._infer_resource_type(obj)
        if inferred_resource_type != self.resourceType:
            raise ValueError(
                f"Object resourceType {inferred_resource_type!r} does not match datasource "
                f"resourceType {self.resourceType!r}."
            )
        payload = self._serialize_object(obj)

        method = "POST"
        path = self.resource["path"]
        if update:
            identifier = payload.get(self.resource["id_field"])
            if identifier is None:
                raise ValueError(
                    f"Update requires {self.resource['id_field']!r} in the serialized payload for "
                    f"{self.resourceType}."
                )
            method = "PUT"
            path = f"{path}/{quote(str(identifier))}"

        request_params = self._build_query_params(view=view)
        saved = self._request_json(method, path, params=request_params, json_body=payload)
        return self.extend(self._hydrate(saved, raw=isinstance(obj, Mapping)))

    def validate(
        self,
        obj: Any,
        update: bool = False,
        *,
        view: str | None = None,
    ) -> ValidationResponse:
        inferred_resource_type = self._infer_resource_type(obj)
        if inferred_resource_type != self.resourceType:
            raise ValueError(
                f"Object resourceType {inferred_resource_type!r} does not match datasource "
                f"resourceType {self.resourceType!r}."
            )

        payload = self._serialize_object(obj)
        request_params = self._build_query_params(view=view)
        validation_payload = self._build_validation_payload(payload, update=update)
        return ValidationResponse.model_validate(
            self._request_json(
                "POST",
                f"{self.resource['path']}/{self.VALIDATE_PATH}",
                params=request_params,
                json_body=validation_payload,
            )
        )

    def _query(
        self,
        resource_path: str,
        *,
        query: str | None = None,
        page_size: int = 50,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        query_params = self._build_query_params(
            params=params,
            template=template,
            view=view,
        )
        if query:
            query_params["q"] = query
        yield from self._paginate(f"{resource_path}/search", params=query_params, page_size=page_size)

    def _build_query_params(
        self,
        *,
        params: Mapping[str, Any] | None = None,
        template: Mapping[str, Any] | str | None = None,
        view: str | None = None,
    ) -> dict[str, Any]:
        query_params = dict(params or {})
        if template is None:
            self._apply_standard_api_params(
                query_params,
                view=view,
            )
            return query_params
        if isinstance(template, str) and view is None:
            query_params.setdefault("view", template)
        elif isinstance(template, Mapping):
            query_params.update(template)
        self._apply_standard_api_params(
            query_params,
            view=view,
        )
        return query_params

    def _apply_standard_api_params(
        self,
        params: dict[str, Any],
        *,
        view: str | None = None,
    ) -> None:
        if view is not None:
            params.setdefault("view", view)

    def _hydrate(self, payload: dict[str, Any], *, raw: bool) -> Any:
        if raw:
            return payload

        model_class = self._get_model_class()
        model_payload = self._prepare_payload_for_model(model_class, payload)
        return model_class.model_validate(model_payload)

    def _prepare_payload_for_model(self, model_class: Any, payload: dict[str, Any]) -> dict[str, Any]:
        model_fields = getattr(model_class, "model_fields", None)
        if not model_fields:
            return payload
        allowed = set(model_fields)
        for field in model_fields.values():
            alias = getattr(field, "alias", None)
            if alias:
                allowed.add(alias)
        return {key: value for key, value in payload.items() if key in allowed}

    def _build_validation_payload(
        self,
        payload: dict[str, Any],
        *,
        update: bool,
    ) -> dict[str, Any]:
        validation_payload = dict(payload)
        if update:
            validation_payload["_method"] = "PUT"
        return validation_payload

    def _get_model_module(self) -> Any:
        try:
            return import_module("gsrs.model")
        except ModuleNotFoundError as exc:
            if exc.name == "gsrs.model":
                raise ModuleNotFoundError(
                    "gsrs.model is required to use gsrs.datasources.Gsrs."
                ) from exc
            raise

    def _get_model_class(self) -> Any:
        model_module = self._get_model_module()
        model_class = getattr(model_module, self.resource["model_name"], None)
        if model_class is None:
            raise AttributeError(
                f"gsrs.model does not define {self.resource['model_name']!r} required for "
                f"{self.resourceType!r}."
            )
        return model_class

    def _infer_resource_type(self, obj: Any) -> str:
        model_module = self._get_model_module()
        substance_class = getattr(model_module, "Substance", None)
        product_class = getattr(model_module, "Product", None)
        if substance_class is not None and isinstance(obj, substance_class):
            return "Substance"
        if product_class is not None and isinstance(obj, product_class):
            return "Product"

        if isinstance(obj, Mapping):
            explicit = obj.get("resourceType") or obj.get("resource_type")
            if explicit is not None:
                self.get_resource_config(str(explicit))
                return str(explicit)
            if "substanceClass" in obj or "approvalID" in obj or "names" in obj:
                return "Substance"
            if "productProvenances" in obj or "productManufactureItems" in obj or "productContainer" in obj:
                return "Product"

        name = obj.__class__.__name__
        if "Substance" in name:
            return "Substance"
        if name == "Product":
            return "Product"
        raise ValueError(f"Could not infer resourceType from object of type {type(obj).__name__}.")

    def _serialize_object(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, Mapping):
            return dict(obj)
        model_dump = getattr(obj, "model_dump", None)
        if callable(model_dump):
            return model_dump(by_alias=True, exclude_none=True)
        legacy_dict = getattr(obj, "dict", None)
        if callable(legacy_dict):
            return legacy_dict(by_alias=True, exclude_none=True)
        raise TypeError(f"Object of type {type(obj).__name__} cannot be serialized.")
