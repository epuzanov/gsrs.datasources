import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ModelField:
    def __init__(self, alias=None):
        self.alias = alias


class StubModel:
    model_fields = {}

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def model_validate(cls, payload):
        data = {}
        for field_name, field in cls.model_fields.items():
            if field_name in payload:
                data[field_name] = payload[field_name]
                continue
            alias = getattr(field, "alias", None)
            data[field_name] = payload.get(alias) if alias else None
        return cls(**data)


def install_gsrs_model_stub():
    module = types.ModuleType("gsrs.model")

    class Substance(StubModel):
        model_fields = {
            "uuid": ModelField(),
            "substanceClass": ModelField(),
            "names": ModelField(),
            "references": ModelField(),
            "version": ModelField(),
            "selfLink": ModelField(alias="_self"),
        }

        @classmethod
        def _resource_path(cls):
            return "substances"

        @classmethod
        def _id_field(cls):
            return "uuid"

    class Product(StubModel):
        model_fields = {
            "productContainer": ModelField(),
            "language": ModelField(),
            "productProvenances": ModelField(),
            "productManufactureItems": ModelField(),
            "selfLink": ModelField(alias="_self"),
        }

        @classmethod
        def _resource_path(cls):
            return "products"

        @classmethod
        def _id_field(cls):
            return "id"

    module.Substance = Substance
    module.Product = Product
    sys.modules["gsrs.model"] = module

    import gsrs

    setattr(gsrs, "model", module)
    return Substance, Product


Substance, Product = install_gsrs_model_stub()

from gsrs.client import (
    Gsrs,
    LegacyAuthHandler,
    ValidationLink,
    ValidationMessage,
    ValidationResponse,
)
from gsrs.client.http import UrlLibSession

SUBSTANCE_PAYLOAD = {
    "uuid": "00000000-0000-0000-0000-000000000001",
    "substanceClass": "concept",
    "names": [
        {
            "name": "Example Concept",
            "type": "cn",
            "languages": ["en"],
            "nameJurisdiction": [],
            "nameOrgs": [],
            "references": [],
            "access": [],
        }
    ],
    "references": [
        {
            "docType": "SYSTEM",
            "citation": "generated",
            "publicDomain": True,
            "tags": [],
            "access": [],
        }
    ],
    "version": "1",
    "_self": "https://example.test/api/v1/substances/00000000-0000-0000-0000-000000000001",
}

PRODUCT_PAYLOAD = {
    "productContainer": "Bottle",
    "language": "English",
    "productProvenances": [],
    "productManufactureItems": [],
    "_self": "https://example.test/api/v1/products/123?view=full",
}


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    url: str = "https://example.test/api/v1"
    headers: dict[str, str] | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(self.payload)


class FakeSession:
    """Captures requests and delegates to ``handler``.

    ``Http._request`` passes a pre-serialized JSON body through the ``data``
    keyword, so the signature mirrors that of :class:`UrlLibSession`.
    """

    def __init__(self, handler):
        self._handler = handler
        self.calls = []
        self.close_calls = 0

    def request(self, method, url, *, headers=None, data=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "data": data,
                "timeout": timeout,
            }
        )
        return self._handler(method, url, headers=headers or {}, data=data, timeout=timeout)

    def close(self):
        self.close_calls += 1


class FakeHttpOpener:
    def __init__(self, body=b"{}", url="https://example.test/api/v1/substances"):
        self.body = body
        self.url = url
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append({"request": request, "timeout": timeout})
        return FakeUrlLibResponse(self.body, self.url)


class FakeHeaders(dict):
    def get_content_charset(self, default="utf-8"):
        return default


class FakeUrlLibResponse:
    def __init__(self, body, url):
        self._body = body
        self._url = url
        self.headers = FakeHeaders({"Content-Type": "application/json"})
        self.status = 200
        self.code = 200
        self.msg = "OK"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def info(self):
        return self.headers

    def read(self):
        return self._body


class GsrsClientTests(unittest.TestCase):
    def test_raw_mode_passes_payloads_through_unchanged(self):
        client = Gsrs(
            base_url="https://example.test/api/v1",
            session=FakeSession(lambda method, url, **kwargs: FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)),
        )

        self.assertIsNone(client.resource_type)
        self.assertIsNone(client.id_field)
        self.assertEqual(client.resource_path, "")
        self.assertEqual(client.get(SUBSTANCE_PAYLOAD["uuid"]), SUBSTANCE_PAYLOAD)

    def test_resource_type_accepts_a_model_class(self):
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(lambda *args, **kwargs: None),
        )

        self.assertIs(client.resource_type, Substance)
        self.assertEqual(client.resource_path, "substances")
        self.assertEqual(client.id_field, "uuid")

    def test_resource_type_defaults_id_field_per_model(self):
        client = Gsrs(
            resourceType=Product,
            base_url="https://example.test/api/v1",
            session=FakeSession(lambda *args, **kwargs: None),
        )

        self.assertEqual(client.resource_path, "products")
        self.assertEqual(client.id_field, "id")

    def test_search_returns_id_strings(self):
        def handler(method, url, **kwargs):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            skip = int(query.get("skip", ["0"])[0])
            if skip == 0:
                payload = {
                    "content": [
                        {"idString": "00000000-0000-0000-0000-000000000001"},
                        {"idString": "00000000-0000-0000-0000-000000000002"},
                    ],
                    "total": 3,
                }
            else:
                payload = {
                    "content": [{"idString": "00000000-0000-0000-0000-000000000003"}],
                    "total": 3,
                }
            return FakeResponse(payload=payload, url=url)

        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = client.search("name:example")

        self.assertEqual(
            result,
            [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ],
        )

    def test_search_requests_the_key_view_and_pages_by_fifty(self):
        def handler(method, url, **kwargs):
            return FakeResponse(
                payload={"content": [{"idString": "abc"}], "count": 1},
                url=url,
            )

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        client.search("name:example")

        parsed = urlparse(session.calls[0]["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v1/substances/search")
        self.assertEqual(query["q"], ["name:example"])
        self.assertEqual(query["view"], ["key"])
        self.assertEqual(query["top"], ["50"])

    def test_search_rejects_a_result_without_an_id_string(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload={"content": [{"uuid": "abc"}], "count": 1}, url=url)

        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        with self.assertRaisesRegex(ValueError, "idString"):
            client.search("name:example")

    def test_iterate_yields_typed_objects_and_raw_payloads(self):
        def handler(method, url, **kwargs):
            if "/substances/search" in url:
                return FakeResponse(payload={"content": [SUBSTANCE_PAYLOAD], "count": 1}, url=url)
            if "/products/search" in url:
                return FakeResponse(
                    payload={"content": [dict(PRODUCT_PAYLOAD, uuid="product-uuid")], "count": 1},
                    url=url,
                )
            if urlparse(url).path.endswith("/search"):
                # Raw mode has no entity segment, so requests hit base_url directly.
                return FakeResponse(
                    payload={"content": [dict(PRODUCT_PAYLOAD, uuid="product-uuid")], "count": 1},
                    url=url,
                )
            raise AssertionError(f"Unexpected URL {url}")

        substance_client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )
        product_client = Gsrs(
            resourceType=Product,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )
        raw_client = Gsrs(
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        typed = list(substance_client.iterate("name:example"))
        raw = list(raw_client.iterate("name:example"))

        self.assertEqual(len(typed), 1)
        self.assertIsInstance(typed[0], Substance)
        self.assertEqual(typed[0].uuid, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(raw, [dict(PRODUCT_PAYLOAD, uuid="product-uuid")])
        self.assertIsInstance(product_client.iterate("name:example").__next__(), Product)

    def test_get_supports_raw_and_typed_results(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        typed_client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )
        raw_client = Gsrs(
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        raw = raw_client.get(SUBSTANCE_PAYLOAD["uuid"])
        typed = typed_client.get(SUBSTANCE_PAYLOAD["uuid"])

        self.assertEqual(raw, SUBSTANCE_PAYLOAD)
        self.assertIsInstance(typed, Substance)
        self.assertEqual(str(typed.uuid), SUBSTANCE_PAYLOAD["uuid"])
        self.assertEqual(typed.selfLink, SUBSTANCE_PAYLOAD["_self"])

    def test_get_typed_product_when_model_is_available(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=PRODUCT_PAYLOAD, url=url)

        client = Gsrs(
            resourceType=Product,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        product = client.get("123")

        self.assertIsInstance(product, Product)
        self.assertEqual(product.productContainer, "Bottle")
        self.assertEqual(product.selfLink, PRODUCT_PAYLOAD["_self"])

    def test_save_posts_to_the_collection_and_casts_the_result(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        saved = client.save(
            {"uuid": None, "substanceClass": "concept"},
        )

        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertEqual(urlparse(session.calls[0]["url"]).path, "/api/v1/substances")
        self.assertNotIn("view", parse_qs(urlparse(session.calls[0]["url"]).query))
        self.assertEqual(session.calls[0]["headers"]["Content-Type"], "application/json")
        self.assertIsInstance(saved, Substance)
        self.assertEqual(saved.selfLink, SUBSTANCE_PAYLOAD["_self"])

    def test_save_puts_to_the_identified_record(self):
        def handler(method, url, **kwargs):
            if method == "GET":
                return FakeResponse(payload=7, url=url)
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        client.save({"uuid": SUBSTANCE_PAYLOAD["uuid"], "version": 1})

        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(
            urlparse(session.calls[0]["url"]).path,
            f"/api/v1/substances/{SUBSTANCE_PAYLOAD['uuid']}/version",
        )
        self.assertEqual(session.calls[1]["method"], "PUT")
        self.assertEqual(
            urlparse(session.calls[1]["url"]).path,
            f"/api/v1/substances/{SUBSTANCE_PAYLOAD['uuid']}",
        )
        payload = json.loads(session.calls[1]["data"])
        self.assertEqual(payload["version"], 7)

    def test_validate_posts_to_validation_endpoint_and_returns_raw_response(self):
        validation_response = {
            "valid": True,
            "messages": [
                {
                    "_discriminator": "GinasProcessingMessage",
                    "message": "Looks good.",
                    "messageType": "INFO",
                    "actionType": "IGNORE",
                    "messageId": "W0000001",
                    "suggestedChange": False,
                    "appliedChange": False,
                    "links": [],
                }
            ],
        }

        def handler(method, url, **kwargs):
            if method != "POST":
                raise AssertionError(f"Unexpected method {method}")
            return FakeResponse(payload=validation_response, url=url)

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        result = client.validate(
            dict(SUBSTANCE_PAYLOAD, resourceType="Substance"),
        )

        parsed = urlparse(session.calls[0]["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v1/substances/@validate")
        self.assertNotIn("view", query)
        self.assertIsInstance(result, ValidationResponse)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], ValidationMessage)
        self.assertEqual(result.messages[0].discriminator, "GinasProcessingMessage")
        self.assertEqual(result.messages[0].message, "Looks good.")
        self.assertEqual(result.messages[0].messageType, "INFO")
        self.assertEqual(result.messages[0].actionType, "IGNORE")
        self.assertEqual(result.messages[0].messageId, "W0000001")
        self.assertFalse(result.messages[0].suggestedChange)
        self.assertFalse(result.messages[0].appliedChange)
        self.assertEqual(
            json.loads(session.calls[0]["data"])["substanceClass"],
            "concept",
        )

    def test_validate_is_post_only(self):
        def handler(method, url, **kwargs):
            if method != "POST":
                raise AssertionError(f"Unexpected method {method}")
            return FakeResponse(payload={"valid": True}, url=url)

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        client.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

        self.assertEqual(session.calls[0]["method"], "POST")
        query = parse_qs(urlparse(session.calls[0]["url"]).query)
        self.assertEqual(query, {})

    def test_validate_does_not_accept_an_update_flag(self):
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(lambda *args, **kwargs: FakeResponse(payload={"valid": True})),
        )

        with self.assertRaises(TypeError):
            client.validate({"uuid": "abc"}, update=True)

    def test_validate_accepts_alternate_validation_field_names(self):
        def handler(method, url, **kwargs):
            return FakeResponse(
                payload={
                    "isValid": False,
                    "validationMessages": [
                        {
                            "text": "Name is required.",
                            "type": "ERROR",
                            "propertyName": "names",
                        },
                        "References should be reviewed.",
                    ]
                },
                url=url,
            )

        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = client.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

        self.assertFalse(result.valid)
        self.assertEqual(result.messages[0].message, "Name is required.")
        self.assertEqual(result.messages[0].messageType, "ERROR")
        self.assertEqual(result.messages[0].property, "names")
        self.assertEqual(result.messages[1].message, "References should be reviewed.")

    def test_validate_parses_full_gsrs_processing_message_shape(self):
        def handler(method, url, **kwargs):
            return FakeResponse(
                payload={
                    "validationMessages": [
                        {
                            "_discriminator": "GinasProcessingMessage",
                            "messageType": "NOTICE",
                            "actionType": "IGNORE",
                            "messageId": "E4562362",
                            "message": "Substance Povidon K12 appears to be a full duplicate",
                            "suggestedChange": False,
                            "appliedChange": False,
                            "links": [
                                {
                                    "href": "/app/substance/51666-4",
                                    "text": "[51666-4]Povidon K12",
                                }
                            ],
                        }
                    ],
                    "valid": False,
                },
                url=url,
            )

        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = client.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

        self.assertFalse(result.valid)
        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        self.assertEqual(message.discriminator, "GinasProcessingMessage")
        self.assertEqual(message.messageType, "NOTICE")
        self.assertEqual(message.actionType, "IGNORE")
        self.assertEqual(message.messageId, "E4562362")
        self.assertFalse(message.suggestedChange)
        self.assertFalse(message.appliedChange)
        self.assertEqual(len(message.links), 1)
        self.assertIsInstance(message.links[0], ValidationLink)
        self.assertEqual(message.links[0].href, "/app/substance/51666-4")
        self.assertEqual(message.links[0].text, "[51666-4]Povidon K12")

    def test_validate_uses_the_validate_endpoint(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload={"valid": True}, url=url)

        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        client.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

        self.assertTrue(client.VALIDATE_PATH, "@validate")

    def test_approve_calls_the_approve_endpoint_and_casts_the_result(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        session = FakeSession(handler)
        client = Gsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        approved = client.approve(SUBSTANCE_PAYLOAD["uuid"])

        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(
            urlparse(session.calls[0]["url"]).path,
            f"/api/v1/substances/{SUBSTANCE_PAYLOAD['uuid']}/@approve",
        )
        self.assertIsInstance(approved, Substance)

    def test_raw_mode_resolves_requests_against_base_url(self):
        def handler(method, url, **kwargs):
            if urlparse(url).path.endswith("/search"):
                return FakeResponse(payload={"content": [SUBSTANCE_PAYLOAD], "count": 1}, url=url)
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        session = FakeSession(handler)
        client = Gsrs(base_url="https://example.test/api/v1", session=session)

        client.get("abc")
        records = list(client.iterate("name:example"))

        self.assertEqual(urlparse(session.calls[0]["url"]).path, "/api/v1/abc")
        self.assertEqual(urlparse(session.calls[1]["url"]).path, "/api/v1/search")
        self.assertEqual(records, [SUBSTANCE_PAYLOAD])

    def test_close_is_idempotent(self):
        session = FakeSession(lambda *args, **kwargs: FakeResponse(payload={"content": [], "count": 0}))
        client = Gsrs(resourceType=Substance, base_url="https://example.test/api/v1", session=session)

        client.close()
        client.close()

        self.assertEqual(session.close_calls, 0)

    def test_urllib_session_supports_legacy_gsrs_auth_headers(self):
        opener = FakeHttpOpener()
        session = UrlLibSession(
            auth=LegacyAuthHandler("legacy-user", "legacy-pass"),
            opener=opener,
        )

        session.request("GET", "https://example.test/api/v1/substances")

        headers = dict(opener.requests[0]["request"].header_items())
        self.assertEqual(headers["Auth-username"], "legacy-user")
        self.assertEqual(headers["Auth-password"], "legacy-pass")


if __name__ == "__main__":
    unittest.main()
