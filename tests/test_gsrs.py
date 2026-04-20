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

    class Product(StubModel):
        model_fields = {
            "productContainer": ModelField(),
            "language": ModelField(),
            "productProvenances": ModelField(),
            "productManufactureItems": ModelField(),
            "selfLink": ModelField(alias="_self"),
        }

    module.Substance = Substance
    module.Product = Product
    sys.modules["gsrs.model"] = module

    import gsrs

    setattr(gsrs, "model", module)
    return Substance, Product


Substance, Product = install_gsrs_model_stub()

from gsrs.datasources import Gsrs, ValidationLink, ValidationMessage, ValidationResponse
from gsrs.datasources.http import UrlLibSession


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
    def __init__(self, handler):
        self._handler = handler
        self.calls = []
        self.close_calls = 0

    def request(self, method, url, *, headers=None, json_body=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json_body": json_body,
                "timeout": timeout,
            }
        )
        return self._handler(method, url, headers=headers or {}, json_body=json_body, timeout=timeout)

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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self):
        return self._body


class GsrsDatasourceTests(unittest.TestCase):
    def test_model_class_is_required_for_hydration(self):
        import gsrs

        original_module = sys.modules["gsrs.model"]
        replacement = types.ModuleType("gsrs.model")
        replacement.Product = getattr(original_module, "Product", None)

        sys.modules["gsrs.model"] = replacement
        gsrs.__dict__["model"] = replacement
        self.addCleanup(sys.modules.__setitem__, "gsrs.model", original_module)
        self.addCleanup(gsrs.__dict__.__setitem__, "model", original_module)

        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(lambda method, url, **kwargs: FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)),
        )

        with self.assertRaisesRegex(AttributeError, "does not define 'Substance'"):
            datasource.get(SUBSTANCE_PAYLOAD["uuid"])

    def test_resource_type_validation(self):
        with self.assertRaisesRegex(ValueError, "Unsupported resourceType"):
            Gsrs(
                resourceType="Invalid",
                base_url="https://example.test/api/v1",
                session=FakeSession(lambda *args, **kwargs: None),
            )

    def test_search_returns_uuid_list(self):
        def handler(method, url, **kwargs):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            skip = int(query.get("skip", ["0"])[0])
            if skip == 0:
                payload = {
                    "content": [
                        {"uuid": "00000000-0000-0000-0000-000000000001"},
                        {"uuid": "00000000-0000-0000-0000-000000000002"},
                    ],
                    "count": 3,
                }
            else:
                payload = {
                    "content": [{"uuid": "00000000-0000-0000-0000-000000000003"}],
                    "count": 3,
                }
            return FakeResponse(payload=payload, url=url)

        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = datasource.search("name:example", page_size=2)

        self.assertEqual(
            result,
            [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ],
        )

    def test_search_supports_gsrs_view_param(self):
        def handler(method, url, **kwargs):
            return FakeResponse(
                payload={"content": [{"uuid": "00000000-0000-0000-0000-000000000001"}], "count": 1},
                url=url,
            )

        session = FakeSession(handler)
        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=session,
        )

        datasource.search(
            "name:example",
            view=Gsrs.VIEW_COMPACT,
        )

        parsed = urlparse(session.calls[0]["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(query["view"], [Gsrs.VIEW_COMPACT])

    def test_iterate_yields_typed_objects_and_raw_payloads(self):
        def handler(method, url, **kwargs):
            if "/substances/search" in url:
                return FakeResponse(payload={"content": [SUBSTANCE_PAYLOAD], "count": 1}, url=url)
            if "/products/search" in url:
                return FakeResponse(
                    payload={"content": [dict(PRODUCT_PAYLOAD, uuid="product-uuid")], "count": 1},
                    url=url,
                )
            raise AssertionError(f"Unexpected URL {url}")

        substance_datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )
        product_datasource = Gsrs(
            resourceType="Product",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        typed = list(substance_datasource.iterate("name:example"))
        raw = list(product_datasource.iterate("name:example", raw=True))

        self.assertEqual(len(typed), 1)
        self.assertIsInstance(typed[0], Substance)
        self.assertEqual(typed[0].uuid, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(raw, [dict(PRODUCT_PAYLOAD, uuid="product-uuid")])

    def test_get_supports_raw_and_typed_results(self):
        def handler(method, url, **kwargs):
            if "/substances/" not in url:
                raise AssertionError(f"Unexpected URL {url}")
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        raw = datasource.get(SUBSTANCE_PAYLOAD["uuid"], raw=True)
        typed = datasource.get(SUBSTANCE_PAYLOAD["uuid"])

        self.assertEqual(raw, SUBSTANCE_PAYLOAD)
        self.assertIsInstance(typed, Substance)
        self.assertEqual(str(typed.uuid), SUBSTANCE_PAYLOAD["uuid"])
        self.assertEqual(typed.selfLink, SUBSTANCE_PAYLOAD["_self"])

    def test_get_typed_product_when_model_is_available(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=PRODUCT_PAYLOAD, url=url)

        datasource = Gsrs(
            resourceType="Product",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        product = datasource.get("123")

        self.assertIsInstance(product, Product)
        self.assertEqual(product.productContainer, "Bottle")
        self.assertEqual(product.selfLink, PRODUCT_PAYLOAD["_self"])

    def test_save_supports_view_param(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload=SUBSTANCE_PAYLOAD, url=url)

        session = FakeSession(handler)
        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=session,
        )

        saved = datasource.save(
            dict(SUBSTANCE_PAYLOAD, resourceType="Substance"),
            update=True,
            view=Gsrs.VIEW_KEY,
        )

        parsed = urlparse(session.calls[0]["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(query["view"], [Gsrs.VIEW_KEY])
        self.assertEqual(saved["_self"], SUBSTANCE_PAYLOAD["_self"])

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
        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=session,
        )

        result = datasource.validate(
            dict(SUBSTANCE_PAYLOAD, resourceType="Substance"),
            view=Gsrs.VIEW_FULL,
        )

        parsed = urlparse(session.calls[0]["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/v1/substances/@validate")
        self.assertEqual(query["view"], [Gsrs.VIEW_FULL])
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
            session.calls[0]["json_body"]["resourceType"],
            "Substance",
        )

    def test_validate_marks_update_requests(self):
        def handler(method, url, **kwargs):
            return FakeResponse(payload={"valid": True}, url=url)

        session = FakeSession(handler)
        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=session,
        )

        datasource.validate(
            dict(SUBSTANCE_PAYLOAD, resourceType="Substance"),
            update=True,
        )

        self.assertEqual(session.calls[0]["json_body"]["_method"], "PUT")

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

        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = datasource.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

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

        datasource = Gsrs(
            resourceType="Substance",
            base_url="https://example.test/api/v1",
            session=FakeSession(handler),
        )

        result = datasource.validate(dict(SUBSTANCE_PAYLOAD, resourceType="Substance"))

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

    def test_close_is_idempotent(self):
        session = FakeSession(lambda *args, **kwargs: FakeResponse(payload={"content": [], "count": 0}))
        datasource = Gsrs(resourceType="Substance", base_url="https://example.test/api/v1", session=session)

        datasource.close()
        datasource.close()

        self.assertEqual(session.close_calls, 0)

    def test_urllib_session_supports_legacy_gsrs_auth_headers(self):
        opener = FakeHttpOpener()
        session = UrlLibSession(
            legacy_auth=("legacy-user", "legacy-pass"),
            opener=opener,
        )

        session.request("GET", "https://example.test/api/v1/substances")

        headers = dict(opener.requests[0]["request"].header_items())
        self.assertEqual(headers["Auth-username"], "legacy-user")
        self.assertEqual(headers["Auth-password"], "legacy-pass")


if __name__ == "__main__":
    unittest.main()
