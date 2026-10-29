import base64
import io
import json
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import (
    AbstractBasicAuthHandler,
    HTTPPasswordMgr,
    HTTPSHandler,
    Request,
)

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gsrs.datasources
from gsrs.datasources import (
    DEFAULT_SESSION_COOKIE_NAME,
    ApiKeyAuthHandler,
    AuthHandler,
    BasicAuthHandler,
    BearerAuthHandler,
    ComputedTokenAuthHandler,
    Gsrs,
    Http,
    LegacyAuthHandler,
    OAuth2AuthHandler,
    OAuth2Token,
    SessionCookieAuthHandler,
    SsoHeaderAuthHandler,
    TokenAuthHandler,
    compute_gsrs_token,
)
from gsrs.datasources.http import UrlLibSession
from gsrs.exceptions import ApiResponseError, HttpRequestError
from gsrs.transport import (
    _host_matches_no_proxy,
    _normalize_no_proxy,
    _normalize_proxies,
    _ProxyHandler,
)

TOKEN_URL = "https://auth.example.test/oauth2/token"
API_URL = "https://example.test/api/v1/substances"


class FakeHeaders(dict):
    def get_content_charset(self, default="utf-8"):
        return default


class FakeUrlLibResponse:
    def __init__(self, payload, *, status=200, url=API_URL, headers=None):
        self.status = status
        self.code = status
        self.msg = "OK"
        self._url = url
        self.headers = FakeHeaders({"Content-Type": "application/json"})
        if headers:
            self.headers.update(headers)
        if isinstance(payload, bytes):
            self._body = payload
        else:
            self._body = json.dumps(payload).encode("utf-8")

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


class FakeOpener:
    def __init__(self, handler):
        self._handler = handler
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append({"request": request, "timeout": timeout})
        return self._handler(request, timeout)


class TokenIssuer:
    def __init__(self, expires_in=3600, **extra):
        self.count = 0
        self.expires_in = expires_in
        self.extra = extra

    def __call__(self, request, timeout=None):
        self.count += 1
        payload = {
            "access_token": f"token-{self.count}",
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            **self.extra,
        }
        return FakeUrlLibResponse(payload, url=request.full_url)


def make_opener(issuer, api_handler=None):
    def handler(request, timeout=None):
        if request.full_url == TOKEN_URL:
            return issuer(request, timeout)
        if api_handler is not None:
            return api_handler(request, timeout)
        return FakeUrlLibResponse({"ok": True}, url=request.full_url)

    return FakeOpener(handler)


def request_body(request):
    return parse_qs((request.data or b"").decode("utf-8"))


def request_headers(request):
    return {key.lower(): value for key, value in request.header_items()}


def oauth2_config(**overrides):
    config = {
        "token_url": TOKEN_URL,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scope": "read write",
    }
    config.update(overrides)
    return config


def oauth2_handler(opener=None, **overrides):
    config = oauth2_config(**overrides)
    if opener is not None:
        config["opener"] = opener
    return OAuth2AuthHandler(config)


class ConcreteHttp(Http):
    """Minimal concrete Http datasource for exercising shared HTTP behavior."""

    def get(self, id, version=None, template=None):
        return None

    def search(
        self,
        query=None,
        *,
        page_size=50,
        params=None,
        template=None,
    ):
        return []

    def iterate(
        self,
        query=None,
        *,
        page_size=50,
        params=None,
        template=None,
    ):
        return iter(())

    def save(self, obj):
        return obj

    def validate(self, obj):
        return None

    def approve(self, id):
        return None


class ConcreteGsrs(Gsrs):
    """Gsrs datasource with the abstract approve() hook implemented."""

    def approve(self, id):
        return None


class Substance:
    """Minimal stand-in for :class:`gsrs.model.Substance` in auth tests."""

    @classmethod
    def _resource_path(cls):
        return "substances"

    @classmethod
    def _id_field(cls):
        return "uuid"

    @classmethod
    def model_validate(cls, payload):
        return dict(payload)


class OAuth2TokenTests(unittest.TestCase):
    def test_client_credentials_token_is_requested_once_and_reused(self):
        issuer = TokenIssuer()
        opener = make_opener(issuer)
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        first = session.request("GET", API_URL)
        second = session.request("GET", API_URL)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(issuer.count, 1)

        token_request = opener.requests[0]["request"]
        self.assertEqual(token_request.get_method(), "POST")
        self.assertEqual(token_request.full_url, TOKEN_URL)
        self.assertEqual(
            request_body(token_request),
            {"grant_type": ["client_credentials"], "scope": ["read write"]},
        )
        expected_basic = base64.b64encode(b"client-id:client-secret").decode("ascii")
        self.assertEqual(
            request_headers(token_request)["authorization"],
            f"Basic {expected_basic}",
        )
        for entry in opener.requests[1:]:
            self.assertEqual(
                request_headers(entry["request"])["authorization"],
                "Bearer token-1",
            )

    def test_token_is_refreshed_after_expiry(self):
        issuer = TokenIssuer(expires_in=3600)
        opener = make_opener(issuer)
        clock = {"now": 1000.0}

        with patch("gsrs.auth.oauth2.time.monotonic", side_effect=lambda: clock["now"]):
            session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

            session.request("GET", API_URL)
            clock["now"] += 100
            session.request("GET", API_URL)
            self.assertEqual(issuer.count, 1)

            clock["now"] += 4000
            session.request("GET", API_URL)
            self.assertEqual(issuer.count, 2)

        self.assertEqual(
            request_headers(opener.requests[-1]["request"])["authorization"],
            "Bearer token-2",
        )

    def test_401_response_refreshes_token_and_retries_once(self):
        issuer = TokenIssuer()
        api_statuses = [401, 200]

        def api_handler(request, timeout=None):
            status = api_statuses.pop(0)
            return FakeUrlLibResponse({"ok": status == 200}, status=status, url=request.full_url)

        opener = make_opener(issuer, api_handler)
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        response = session.request("GET", API_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(issuer.count, 2)
        self.assertEqual(
            request_headers(opener.requests[-1]["request"])["authorization"],
            "Bearer token-2",
        )

    def test_explicit_authorization_header_skips_oauth2(self):
        issuer = TokenIssuer()
        opener = make_opener(issuer)
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        session.request("GET", API_URL, headers={"Authorization": "Bearer override"})

        self.assertEqual(issuer.count, 0)
        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            "Bearer override",
        )

    def test_password_grant_sends_user_credentials(self):
        issuer = TokenIssuer()
        opener = make_opener(issuer)
        session = UrlLibSession(
            auth=oauth2_handler(
                opener,
                grant_type="password",
                username="gsrs-user",
                password="gsrs-password",
            ),
            opener=opener,
        )

        session.request("GET", API_URL)

        self.assertEqual(
            request_body(opener.requests[0]["request"]),
            {
                "grant_type": ["password"],
                "scope": ["read write"],
                "username": ["gsrs-user"],
                "password": ["gsrs-password"],
            },
        )

    def test_client_credentials_can_be_sent_in_body(self):
        issuer = TokenIssuer()
        opener = make_opener(issuer)
        session = UrlLibSession(
            auth=oauth2_handler(opener, client_auth="body"),
            opener=opener,
        )

        session.request("GET", API_URL)

        token_request = opener.requests[0]["request"]
        self.assertNotIn("authorization", request_headers(token_request))
        self.assertEqual(
            request_body(token_request),
            {
                "grant_type": ["client_credentials"],
                "scope": ["read write"],
                "client_id": ["client-id"],
                "client_secret": ["client-secret"],
            },
        )

    def test_token_provider_from_mapping(self):
        provider = OAuth2Token.from_mapping(oauth2_config())

        self.assertEqual(provider.token_url, TOKEN_URL)
        self.assertEqual(provider.client_id, "client-id")
        self.assertEqual(provider.grant_type, "client_credentials")

    def test_token_endpoint_error_raises_http_request_error(self):
        def token_handler(request, timeout=None):
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                FakeHeaders({"Content-Type": "application/json"}),
                io.BytesIO(b'{"error": "invalid_client"}'),
            )

        opener = FakeOpener(token_handler)
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        with self.assertRaises(HttpRequestError) as raised:
            session.request("GET", API_URL)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.payload, {"error": "invalid_client"})

    def test_token_response_without_access_token_raises_api_response_error(self):
        opener = FakeOpener(
            lambda request, timeout=None: FakeUrlLibResponse(
                {"token_type": "Bearer"},
                url=request.full_url,
            )
        )
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        with self.assertRaisesRegex(ApiResponseError, "did not include 'access_token'"):
            session.request("GET", API_URL)

    def test_invalid_expires_in_raises_api_response_error(self):
        opener = FakeOpener(
            lambda request, timeout=None: FakeUrlLibResponse(
                {"access_token": "token", "expires_in": "soon"},
                url=request.full_url,
            )
        )
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)

        with self.assertRaisesRegex(ApiResponseError, "invalid 'expires_in'"):
            session.request("GET", API_URL)


class OAuth2ConfigurationTests(unittest.TestCase):
    def test_static_bearer_token_is_used(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=BearerAuthHandler("static-token"), opener=opener)

        session.request("GET", API_URL)

        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            "Bearer static-token",
        )

    def test_auth_must_be_auth_handler(self):
        with self.assertRaisesRegex(TypeError, "AuthHandler"):
            UrlLibSession(auth=("user", "password"))

        with self.assertRaisesRegex(TypeError, "AuthHandler"):
            UrlLibSession(auth="Basic abc")

        with self.assertRaisesRegex(TypeError, "AuthHandler"):
            ConcreteHttp(
                resourceType=Substance,
                base_url="https://example.test/api/v1",
                auth=("user", "password"),
            )

    def test_oauth2_requires_token_url_and_client_id(self):
        with self.assertRaisesRegex(ValueError, "token_url is required"):
            OAuth2Token(token_url="", client_id="client-id")
        with self.assertRaisesRegex(ValueError, "client_id is required"):
            OAuth2Token(token_url=TOKEN_URL, client_id="")

    def test_password_grant_requires_user_credentials(self):
        with self.assertRaisesRegex(ValueError, "requires username and password"):
            OAuth2Token(
                token_url=TOKEN_URL,
                client_id="client-id",
                grant_type="password",
            )

    def test_unsupported_grant_type_and_client_auth_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported OAuth2 grant_type"):
            OAuth2Token(
                token_url=TOKEN_URL,
                client_id="client-id",
                grant_type="implicit",
            )
        with self.assertRaisesRegex(ValueError, "Unsupported OAuth2 client_auth"):
            OAuth2Token(
                token_url=TOKEN_URL,
                client_id="client-id",
                client_auth="query",
            )

    def test_invalid_oauth2_type_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "OAuth2Token or a mapping"):
            OAuth2AuthHandler("not-a-provider")


class SslVerificationTests(unittest.TestCase):
    def get_https_context(self, opener):
        handlers = [
            handler
            for handler in opener.handle_open.get("https", [])
            if isinstance(handler, HTTPSHandler)
        ]
        self.assertTrue(handlers, "opener does not contain an HTTPS handler")
        return handlers[0]._context

    def test_oauth2_token_verifies_certificates_by_default(self):
        token = OAuth2Token(token_url=TOKEN_URL, client_id="client-id")

        self.assertTrue(token.verify_ssl)
        context = self.get_https_context(token._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_oauth2_token_trusts_self_signed_certificates(self):
        token = OAuth2Token(
            token_url=TOKEN_URL,
            client_id="client-id",
            verify_ssl=False,
        )

        self.assertFalse(token.verify_ssl)
        context = self.get_https_context(token._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_oauth2_auth_handler_mapping_passes_verify_ssl(self):
        handler = OAuth2AuthHandler(oauth2_config(verify_ssl=False))

        self.assertFalse(handler._token.verify_ssl)
        context = self.get_https_context(handler._token._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_url_lib_session_verifies_certificates_by_default(self):
        session = UrlLibSession()
        self.addCleanup(session.close)

        self.assertTrue(session.verify_ssl)
        context = self.get_https_context(session._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_url_lib_session_trusts_self_signed_certificates(self):
        session = UrlLibSession(verify_ssl=False)
        self.addCleanup(session.close)

        self.assertFalse(session.verify_ssl)
        context = self.get_https_context(session._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_http_datasource_passes_verify_ssl_to_session(self):
        datasource = ConcreteHttp(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            verify_ssl=False,
        )
        self.addCleanup(datasource.close)

        self.assertFalse(datasource.verify_ssl)
        self.assertIsInstance(datasource._session, UrlLibSession)
        self.assertFalse(datasource._session.verify_ssl)
        context = self.get_https_context(datasource._session._opener)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)


class ProxyConfigurationTests(unittest.TestCase):
    HTTP_API_URL = "http://example.test/api/v1/substances"

    def get_proxy_handler(self, opener):
        handlers = [
            handler for handler in opener.handlers if isinstance(handler, _ProxyHandler)
        ]
        self.assertEqual(len(handlers), 1, "opener does not contain a single proxy handler")
        return handlers[0]

    def test_proxy_url_is_expanded_for_http_and_https(self):
        self.assertEqual(
            _normalize_proxies("http://proxy.local:3128"),
            {
                "http": "http://proxy.local:3128",
                "https": "http://proxy.local:3128",
            },
        )

    def test_proxy_url_without_scheme_defaults_to_http(self):
        self.assertEqual(
            _normalize_proxies("proxy.local:3128"),
            {
                "http": "http://proxy.local:3128",
                "https": "http://proxy.local:3128",
            },
        )

    def test_proxy_mapping_is_normalized(self):
        self.assertEqual(
            _normalize_proxies({"HTTP": "proxy.local:3128", "all": "http://fallback:8080"}),
            {
                "http": "http://proxy.local:3128",
                "https": "http://fallback:8080",
            },
        )
        self.assertIsNone(_normalize_proxies(None))
        self.assertIsNone(_normalize_proxies({}))

    def test_invalid_proxy_configuration_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "proxy URL string or a mapping"):
            _normalize_proxies(1234)
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            _normalize_proxies("  ")
        with self.assertRaisesRegex(TypeError, "Proxy URLs must be strings"):
            _normalize_proxies({"http": 1234})
        with self.assertRaisesRegex(TypeError, "keys must be strings"):
            _normalize_proxies({1: "http://proxy.local:3128"})

    def test_no_proxy_accepts_strings_and_sequences(self):
        self.assertEqual(
            _normalize_no_proxy("localhost, .Example.Test"),
            ("localhost", ".example.test"),
        )
        self.assertEqual(
            _normalize_no_proxy(["localhost", " example.test ", ""]),
            ("localhost", "example.test"),
        )
        self.assertEqual(_normalize_no_proxy(None), ())
        with self.assertRaisesRegex(TypeError, "comma separated string"):
            _normalize_no_proxy(8080)

    def test_host_matching_against_no_proxy(self):
        entries = ("localhost", "example.test", ".internal.test")

        self.assertTrue(_host_matches_no_proxy("localhost:8080", entries))
        self.assertTrue(_host_matches_no_proxy("example.test", entries))
        self.assertTrue(_host_matches_no_proxy("api.example.test:443", entries))
        self.assertTrue(_host_matches_no_proxy("gsrs.internal.test", entries))
        self.assertFalse(_host_matches_no_proxy("notexample.test", entries))
        self.assertFalse(_host_matches_no_proxy("example.test.evil.test", entries))
        self.assertFalse(_host_matches_no_proxy("other.test", entries))
        self.assertTrue(_host_matches_no_proxy("anything.test", ("*",)))
        self.assertFalse(_host_matches_no_proxy(None, entries))

    def test_session_routes_requests_through_proxy(self):
        session = UrlLibSession(proxy="proxy.local:3128")
        self.addCleanup(session.close)

        handler = self.get_proxy_handler(session._opener)
        self.assertEqual(handler.proxies["http"], "http://proxy.local:3128")
        self.assertEqual(handler.proxies["https"], "http://proxy.local:3128")

        request = Request(self.HTTP_API_URL)
        self.assertIsNone(handler.proxy_open(request, handler.proxies["http"], "http"))
        self.assertEqual(request.host, "proxy.local:3128")
        self.assertIn(self.HTTP_API_URL, request.full_url)

    def test_no_proxy_hosts_bypass_the_configured_proxy(self):
        session = UrlLibSession(
            proxy="http://proxy.local:3128",
            no_proxy="example.test",
        )
        self.addCleanup(session.close)

        handler = self.get_proxy_handler(session._opener)
        request = Request(self.HTTP_API_URL)

        self.assertIsNone(handler.proxy_open(request, handler.proxies["http"], "http"))
        self.assertEqual(request.host, "example.test")

    def test_environment_proxy_settings_are_used(self):
        environment = {
            "http_proxy": "http://env-proxy.local:3128",
            "https_proxy": "http://env-secure-proxy.local:3128",
            "no_proxy": "localhost,internal.test",
        }

        with patch.dict("os.environ", environment):
            session = UrlLibSession()
            self.addCleanup(session.close)

            handler = self.get_proxy_handler(session._opener)
            self.assertEqual(handler.proxies["http"], "http://env-proxy.local:3128")
            self.assertEqual(handler.proxies["https"], "http://env-secure-proxy.local:3128")
            self.assertNotIn("no", handler.proxies)

            bypassed = Request("http://internal.test/api/v1/substances")
            self.assertIsNone(handler.proxy_open(bypassed, handler.proxies["http"], "http"))
            self.assertEqual(bypassed.host, "internal.test")

    def test_explicit_no_proxy_filters_environment_proxies(self):
        environment = {
            "http_proxy": "http://env-proxy.local:3128",
            "no_proxy": "environment.test",
        }

        with patch.dict("os.environ", environment):
            session = UrlLibSession(no_proxy=["explicit.test"])
            self.addCleanup(session.close)

        handler = self.get_proxy_handler(session._opener)
        self.assertEqual(session.no_proxy, ("explicit.test",))
        self.assertEqual(handler.proxies["http"], "http://env-proxy.local:3128")

    def test_caller_supplied_opener_owns_transport_configuration(self):
        opener = FakeOpener(lambda request, timeout=None: FakeUrlLibResponse({}, url=request.full_url))
        session = UrlLibSession(proxy="http://proxy.local:3128", opener=opener)
        self.addCleanup(session.close)

        session.request("GET", self.HTTP_API_URL)

        self.assertEqual(opener.requests[0]["request"].host, "example.test")
        self.assertEqual(session.proxy, {"http": "http://proxy.local:3128", "https": "http://proxy.local:3128"})

    def test_oauth2_token_uses_configured_proxy(self):
        token = OAuth2Token(
            token_url=TOKEN_URL,
            client_id="client-id",
            proxy="http://proxy.local:3128",
            no_proxy=["localhost"],
        )

        handler = self.get_proxy_handler(token._opener)
        self.assertEqual(handler.proxies["https"], "http://proxy.local:3128")
        self.assertEqual(handler.no_proxy, ("localhost",))
        self.assertEqual(token.proxy, {"http": "http://proxy.local:3128", "https": "http://proxy.local:3128"})
        self.assertEqual(token.no_proxy, ("localhost",))

    def test_oauth2_auth_handler_mapping_passes_proxy(self):
        handler = OAuth2AuthHandler(
            oauth2_config(proxy="http://proxy.local:3128", no_proxy="localhost")
        )

        proxy_handler = self.get_proxy_handler(handler._token._opener)
        self.assertEqual(proxy_handler.proxies["http"], "http://proxy.local:3128")
        self.assertEqual(handler._token.no_proxy, ("localhost",))

    def test_http_datasource_passes_proxy_to_session(self):
        datasource = ConcreteHttp(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            proxy="http://proxy.local:3128",
            no_proxy="localhost",
        )
        self.addCleanup(datasource.close)

        self.assertIsInstance(datasource._session, UrlLibSession)
        self.assertEqual(
            datasource.proxy,
            {"http": "http://proxy.local:3128", "https": "http://proxy.local:3128"},
        )
        self.assertEqual(datasource.no_proxy, ("localhost",))
        proxy_handler = self.get_proxy_handler(datasource._session._opener)
        self.assertEqual(proxy_handler.proxies["https"], "http://proxy.local:3128")


class OAuth2DatasourceTests(unittest.TestCase):
    def test_http_datasource_uses_static_bearer_token(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=BearerAuthHandler("static-token"), opener=opener)
        datasource = ConcreteHttp(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        datasource._request_json("GET", "substances")

        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            "Bearer static-token",
        )

    def test_gsrs_datasource_configures_oauth2_handler(self):
        handler = OAuth2AuthHandler(oauth2_config())
        datasource = ConcreteGsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            auth=handler,
        )
        self.addCleanup(datasource.close)

        self.assertIs(datasource._session._auth, handler)
        self.assertIsInstance(handler, AuthHandler)
        self.assertIsInstance(handler, OAuth2AuthHandler)
        self.assertIsInstance(handler, AbstractBasicAuthHandler)

    def test_gsrs_datasource_uses_oauth2_bearer_token(self):
        issuer = TokenIssuer()

        def api_handler(request, timeout=None):
            return FakeUrlLibResponse({"uuid": "abc"}, url=request.full_url)

        opener = make_opener(issuer, api_handler)
        session = UrlLibSession(auth=oauth2_handler(opener), opener=opener)
        datasource = ConcreteGsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            session=session,
        )

        record = datasource.get("abc")

        self.assertEqual(record, {"uuid": "abc"})
        self.assertEqual(issuer.count, 1)
        self.assertEqual(
            request_headers(opener.requests[-1]["request"])["authorization"],
            "Bearer token-1",
        )
        self.assertIn("/api/v1/substances/abc", opener.requests[-1]["request"].full_url)


class AuthenticationHandlerTests(unittest.TestCase):
    def test_basic_auth_uses_password_manager(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=BasicAuthHandler("user", "password"), opener=opener)

        session.request("GET", API_URL)

        handler = session._auth_handlers[0]
        self.assertIsInstance(handler, AuthHandler)
        self.assertIsInstance(handler, BasicAuthHandler)
        self.assertIsInstance(handler.passwd, HTTPPasswordMgr)
        expected = base64.b64encode(b"user:password").decode("ascii")
        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            f"Basic {expected}",
        )

    def test_raw_auth_header_uses_auth_handler(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=AuthHandler({"Authorization": "Bearer raw-token"}), opener=opener)

        session.request("GET", API_URL)

        self.assertIsInstance(session._auth_handlers[0], AuthHandler)
        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            "Bearer raw-token",
        )

    def test_legacy_auth_uses_auth_handler(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=LegacyAuthHandler("legacy-user", "legacy-pass"), opener=opener)

        session.request("GET", API_URL)

        self.assertIsInstance(session._auth_handlers[0], AuthHandler)
        self.assertIsInstance(session._auth_handlers[0].passwd, HTTPPasswordMgr)
        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["auth-username"], "legacy-user")
        self.assertEqual(headers["auth-password"], "legacy-pass")

    def test_explicit_authorization_header_overrides_static_bearer(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=BearerAuthHandler("static-token"), opener=opener)

        session.request("GET", API_URL, headers={"Authorization": "Bearer override"})

        self.assertEqual(
            request_headers(opener.requests[0]["request"])["authorization"],
            "Bearer override",
        )


class GsrsLegacyAuthHandlerTests(unittest.TestCase):
    def test_legacy_auth_sends_username_and_password_headers(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=LegacyAuthHandler("admin", "admin"), opener=opener)

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["auth-username"], "admin")
        self.assertEqual(headers["auth-password"], "admin")

    def test_token_auth_sends_auth_token_header(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=TokenAuthHandler("computed-token"), opener=opener)

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["auth-token"], "computed-token")
        self.assertNotIn("auth-username", headers)

    def test_token_auth_supports_callable_tokens(self):
        tokens = iter(["first-token", "second-token"])
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=TokenAuthHandler(lambda: next(tokens)), opener=opener)

        session.request("GET", API_URL)
        session.request("GET", API_URL)

        self.assertEqual(
            request_headers(opener.requests[0]["request"])["auth-token"],
            "first-token",
        )
        self.assertEqual(
            request_headers(opener.requests[1]["request"])["auth-token"],
            "second-token",
        )

    def test_token_auth_rejects_invalid_token_arguments(self):
        with self.assertRaises(TypeError):
            TokenAuthHandler(42)
        with self.assertRaises(ValueError):
            TokenAuthHandler("token", header="")

    def test_computed_token_matches_upstream_algorithm(self):
        token = compute_gsrs_token(
            "admin",
            "BPwnt6sw8yTSfOqjjhNr",
            time_resolution_ms=1000,
            timestamp_ms=5_000,
        )

        import hashlib

        expected = hashlib.sha1(b"5adminBPwnt6sw8yTSfOqjjhNr").hexdigest()
        self.assertEqual(token, expected)

    def test_computed_token_handler_sends_auth_token_header(self):
        opener = make_opener(TokenIssuer())
        handler = ComputedTokenAuthHandler(
            "admin",
            "api-key",
            time_resolution_ms=86_400_000,
        )
        session = UrlLibSession(auth=handler, opener=opener)

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["auth-token"], compute_gsrs_token("admin", "api-key"))

    def test_computed_token_rejects_missing_arguments(self):
        with self.assertRaises(ValueError):
            ComputedTokenAuthHandler("", "key")
        with self.assertRaises(ValueError):
            ComputedTokenAuthHandler("admin", "")
        with self.assertRaises(ValueError):
            compute_gsrs_token("admin", "key", time_resolution_ms=0)

    def test_api_key_sends_auth_key_and_username_headers(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(
            auth=ApiKeyAuthHandler("api-key", username="admin"),
            opener=opener,
        )

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["auth-key"], "api-key")
        self.assertEqual(headers["auth-username"], "admin")

    def test_api_key_can_use_alternative_headers(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(
            auth=ApiKeyAuthHandler(
                "api-key",
                username="admin",
                key_header="X-Api-Key",
                user_header=None,
            ),
            opener=opener,
        )

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["x-api-key"], "api-key")
        self.assertNotIn("auth-username", headers)
        self.assertNotIn("auth-key", headers)

    def test_api_key_rejects_empty_key(self):
        with self.assertRaises(ValueError):
            ApiKeyAuthHandler("")

    def test_sso_handler_sends_configured_headers(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(
            auth=SsoHeaderAuthHandler(
                "sso-user",
                username_header="OAM_REMOTE_USER",
                email="sso@example.test",
                email_header="OAM_REMOTE_EMAIL",
                roles=["Query", "Updater"],
                roles_header="OAM_REMOTE_ROLES",
            ),
            opener=opener,
        )

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["oam_remote_user"], "sso-user")
        self.assertEqual(headers["oam_remote_email"], "sso@example.test")
        self.assertEqual(headers["oam_remote_roles"], "Query;Updater")

    def test_sso_handler_without_optional_fields_sends_only_username(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=SsoHeaderAuthHandler("sso-user"), opener=opener)

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["oam_remote_user"], "sso-user")
        self.assertEqual([key for key in headers if key.startswith("oam")], ["oam_remote_user"])

    def test_sso_handler_requires_headers_for_optional_values(self):
        with self.assertRaises(ValueError):
            SsoHeaderAuthHandler("sso-user", email="sso@example.test")
        with self.assertRaises(ValueError):
            SsoHeaderAuthHandler("sso-user", roles=["Query"])
        with self.assertRaises(ValueError):
            SsoHeaderAuthHandler("")

    def test_session_cookie_sends_cookie_header(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(auth=SessionCookieAuthHandler("session-id"), opener=opener)

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["cookie"], "ix.session=session-id")

    def test_session_cookie_can_use_a_custom_cookie_name(self):
        opener = make_opener(TokenIssuer())
        session = UrlLibSession(
            auth=SessionCookieAuthHandler("session-id", cookie_name="gsrs.session"),
            opener=opener,
        )

        session.request("GET", API_URL)

        headers = request_headers(opener.requests[0]["request"])
        self.assertEqual(headers["cookie"], "gsrs.session=session-id")

    def test_session_cookie_is_captured_from_response(self):
        def handler(request, timeout=None):
            return FakeUrlLibResponse(
                {"ok": True},
                url=request.full_url,
                headers={"Set-Cookie": "ix.session=captured-id; Path=/; HttpOnly"},
            )

        auth = SessionCookieAuthHandler()
        opener = FakeOpener(handler)
        session = UrlLibSession(auth=auth, opener=opener)

        session.request("GET", API_URL)

        self.assertEqual(auth.session_id, "captured-id")
        self.assertEqual(session.request("GET", API_URL).status_code, 200)
        self.assertEqual(
            request_headers(opener.requests[1]["request"])["cookie"],
            "ix.session=captured-id",
        )

    def test_session_cookie_capture_can_be_disabled(self):
        def handler(request, timeout=None):
            return FakeUrlLibResponse(
                {"ok": True},
                url=request.full_url,
                headers={"Set-Cookie": "ix.session=captured-id; Path=/"},
            )

        auth = SessionCookieAuthHandler(capture=False)
        session = UrlLibSession(auth=auth, opener=FakeOpener(handler))

        session.request("GET", API_URL)

        self.assertIsNone(auth.session_id)

    def test_session_cookie_logs_in_with_credentials_and_reuses_the_cookie(self):
        def handler(request, timeout=None):
            return FakeUrlLibResponse(
                {"ok": True},
                url=request.full_url,
                headers={"Set-Cookie": "ix.session=captured-id; Path=/; HttpOnly"},
            )

        auth = SessionCookieAuthHandler(credentials=LegacyAuthHandler("admin", "admin"))
        opener = FakeOpener(handler)
        session = UrlLibSession(auth=auth, opener=opener)

        session.request("GET", API_URL)

        first = request_headers(opener.requests[0]["request"])
        self.assertEqual(first["auth-username"], "admin")
        self.assertEqual(first["auth-password"], "admin")
        self.assertNotIn("cookie", first)

        session.request("GET", API_URL)

        second = request_headers(opener.requests[1]["request"])
        self.assertEqual(second["cookie"], "ix.session=captured-id")
        # Credentials are still sent so GSRS can recover from an expired session.
        self.assertEqual(second["auth-username"], "admin")

    def test_session_cookie_rejects_invalid_credentials(self):
        with self.assertRaises(TypeError):
            SessionCookieAuthHandler(credentials={"auth-username": "admin"})

    def test_explicit_session_cookie_is_not_overwritten(self):
        def handler(request, timeout=None):
            return FakeUrlLibResponse(
                {"ok": True},
                url=request.full_url,
                headers={"Set-Cookie": "ix.session=other-id; Path=/"},
            )

        auth = SessionCookieAuthHandler("explicit-id")
        session = UrlLibSession(auth=auth, opener=FakeOpener(handler))

        session.request("GET", API_URL)

        self.assertEqual(auth.session_id, "explicit-id")

    def test_session_cookie_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            SessionCookieAuthHandler(cookie_name="")
        with self.assertRaises(ValueError):
            SessionCookieAuthHandler(header="")

    def test_gsrs_datasource_accepts_token_auth(self):
        auth = TokenAuthHandler("computed-token")
        opener = make_opener(TokenIssuer())
        datasource = ConcreteGsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            auth=auth,
            session=UrlLibSession(auth=auth, opener=opener),
        )

        try:
            self.assertIsInstance(datasource._session._auth_handlers[0], TokenAuthHandler)
            self.assertIs(datasource._session._auth_handlers[0], auth)
        finally:
            datasource.close()

    def test_whoami_parses_string_role_names(self):
        def handler(request, timeout=None):
            return FakeUrlLibResponse(
                {
                    "identifier": "ADMIN",
                    "key": "api-key",
                    "roles": ["Query", "Admin"],
                    "groups": [],
                },
                url=request.full_url,
            )

        session = UrlLibSession(auth=TokenAuthHandler("token"), opener=FakeOpener(handler))
        datasource = ConcreteGsrs(
            resourceType=Substance,
            base_url="https://example.test/api/v1",
            auth=TokenAuthHandler("token"),
            session=session,
        )

        try:
            payload = datasource.whoami()
        finally:
            datasource.close()

        self.assertEqual(payload.identifier, "ADMIN")
        self.assertEqual([role.role for role in payload.roles], ["Query", "Admin"])


class AuthModuleLayoutTests(unittest.TestCase):
    """The auth handlers live in the ``gsrs.auth`` package."""

    #: Handler name -> the submodule of :mod:`gsrs.auth` that defines it.
    HANDLERS = {
        "ApiKeyAuthHandler": "gsrs.auth.api_key",
        "AuthHandler": "gsrs.auth.base",
        "BasicAuthHandler": "gsrs.auth.basic",
        "BearerAuthHandler": "gsrs.auth.bearer",
        "ComputedTokenAuthHandler": "gsrs.auth.token_header",
        "LegacyAuthHandler": "gsrs.auth.basic",
        "OAuth2AuthHandler": "gsrs.auth.oauth2",
        "SessionCookieAuthHandler": "gsrs.auth.session",
        "SsoHeaderAuthHandler": "gsrs.auth.sso",
        "TokenAuthHandler": "gsrs.auth.token_header",
    }
    CONSTANTS = {
        "DEFAULT_SESSION_COOKIE_NAME": "gsrs.auth.session",
        "DEFAULT_TOKEN_TIME_RESOLUTION_MS": "gsrs.auth.tokens",
    }

    def test_handlers_are_defined_in_the_auth_package(self):
        import gsrs.auth as auth_package

        for name, module in self.HANDLERS.items():
            with self.subTest(name=name):
                handler = getattr(auth_package, name)
                self.assertIs(getattr(gsrs.datasources, name), handler)
                self.assertEqual(handler.__module__, module)

    def test_constants_and_helpers_are_defined_in_the_auth_package(self):
        import gsrs.auth as auth_package

        for name, module in self.CONSTANTS.items():
            with self.subTest(name=name):
                value = getattr(auth_package, name)
                self.assertIs(getattr(gsrs.datasources, name), value)
        self.assertEqual(auth_package.compute_gsrs_token.__module__, "gsrs.auth.tokens")
        self.assertEqual(DEFAULT_SESSION_COOKIE_NAME, "ix.session")

    def test_http_module_reexports_the_auth_surface(self):
        import gsrs.auth as auth_package
        import gsrs.datasources.http as http_module

        for name in (
            *self.HANDLERS,
            *self.CONSTANTS,
            "OAuth2Token",
            "compute_gsrs_token",
        ):
            with self.subTest(name=name):
                self.assertIn(name, http_module.__all__)
                self.assertIs(getattr(http_module, name), getattr(auth_package, name))

    def test_transport_types_stay_in_the_http_module(self):
        import gsrs.datasources.http as http_module

        for name in ("Http", "UrlLibSession"):
            with self.subTest(name=name):
                self.assertEqual(getattr(http_module, name).__module__, "gsrs.datasources.http")

    def test_oauth2_token_lives_with_its_handler(self):
        import gsrs.auth as auth_package
        import gsrs.datasources.http as http_module

        # ``OAuth2Token`` and ``OAuth2AuthHandler`` share a module, so neither
        # needs a deferred import of the other.
        self.assertEqual(OAuth2Token.__module__, "gsrs.auth.oauth2")
        self.assertEqual(OAuth2AuthHandler.__module__, "gsrs.auth.oauth2")
        self.assertIs(http_module.OAuth2Token, OAuth2Token)
        self.assertIn("OAuth2Token", auth_package.__all__)

    def test_http_response_lives_in_the_responses_package(self):
        import gsrs.datasources.http as http_module
        import gsrs.responses as responses_package

        response_type = responses_package.HttpResponse
        self.assertEqual(response_type.__module__, "gsrs.responses.http")
        self.assertIs(http_module.HttpResponse, response_type)

    def test_api_models_are_split_by_domain(self):
        import gsrs.responses as responses_package

        expected = {
            "WhoAmIGroup": "gsrs.responses.whoami",
            "WhoAmIResponse": "gsrs.responses.whoami",
            "WhoAmIRole": "gsrs.responses.whoami",
            "WhoAmIUser": "gsrs.responses.whoami",
            "ValidationLink": "gsrs.responses.validation",
            "ValidationMessage": "gsrs.responses.validation",
            "ValidationResponse": "gsrs.responses.validation",
        }
        for name, module in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(responses_package, name).__module__, module)
        self.assertEqual(
            sorted(responses_package.__all__),
            sorted([*expected, "HttpResponse"]),
        )

    def test_oauth2_auth_handler_still_accepts_a_token_mapping(self):
        handler = oauth2_handler()
        self.assertIsInstance(handler, OAuth2AuthHandler)
        self.assertIsInstance(handler, AbstractBasicAuthHandler)
        self.assertIsInstance(handler._token, OAuth2Token)
        self.assertEqual(handler._token.client_id, "client-id")


class TransportModuleLayoutTests(unittest.TestCase):
    """Proxy/TLS plumbing lives in the ``gsrs.transport`` package."""

    #: Helper name -> the submodule of :mod:`gsrs.transport` that defines it.
    PROXY_HELPERS = {
        "DEFAULT_PROXY_SCHEMES": "gsrs.transport.proxy",
        "_DelegatingHandler": "gsrs.transport.handlers",
        "_ProxyHandler": "gsrs.transport.handlers",
        "_build_proxy_handler": "gsrs.transport.opener",
        "_build_url_opener": "gsrs.transport.opener",
        "_create_ssl_context": "gsrs.transport.tls",
        "_header_values": "gsrs.transport.headers",
        "_host_matches_no_proxy": "gsrs.transport.proxy",
        "_normalize_no_proxy": "gsrs.transport.proxy",
        "_normalize_proxies": "gsrs.transport.proxy",
        "_normalize_proxy_url": "gsrs.transport.proxy",
        "_parse_set_cookie_headers": "gsrs.transport.headers",
        "_strip_host_port": "gsrs.transport.proxy",
    }

    def test_proxy_helpers_are_defined_in_the_transport_package(self):
        import importlib

        import gsrs.transport as transport_package

        for name, module in self.PROXY_HELPERS.items():
            with self.subTest(name=name):
                submodule = importlib.import_module(module)
                self.assertIs(
                    getattr(transport_package, name),
                    getattr(submodule, name),
                    f"{name} should be defined in {module}",
                )

    def test_http_module_reexports_the_transport_surface(self):
        import gsrs.datasources.http as http_module
        import gsrs.transport as transport_package

        # ``http`` re-exports the pieces it actually uses; the remaining private
        # helpers are implementation details of ``transport``.
        for name in (
            "NoProxyConfig",
            "ProxyConfig",
            "_DelegatingHandler",
            "_build_url_opener",
            "_normalize_no_proxy",
            "_normalize_proxies",
            "_parse_set_cookie_headers",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(http_module, name), getattr(transport_package, name))

    def test_transport_types_are_publicly_exported(self):
        import gsrs.transport as transport_package

        self.assertEqual(
            transport_package.__all__,
            ["DEFAULT_PROXY_SCHEMES", "NoProxyConfig", "ProxyConfig"],
        )


class PackageLayeringTests(unittest.TestCase):
    """``transport <- responses/auth <- datasources``, with no cycles."""

    ROOT = Path(__file__).resolve().parents[1] / "gsrs"

    #: Package -> the sibling packages it may import from.
    ALLOWED = {
        "gsrs.transport": set(),
        "gsrs.responses": set(),
        "gsrs.exceptions": set(),
        "gsrs.auth": {"gsrs.transport"},
        "gsrs.datasources": {"gsrs.auth", "gsrs.transport", "gsrs.responses"},
    }

    #: Dependency-free leaf modules that any package may import.
    LEAVES = {"gsrs.exceptions"}

    def _module_name(self, path: Path) -> str:
        relative = path.relative_to(self.ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(["gsrs", *parts])

    def _imports(self, path: Path) -> set[str]:
        import ast

        module = self._module_name(path)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        names: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[: len(base) - (node.level - 1)]
                    target = ".".join([*base, node.module]) if node.module else ".".join(base)
                else:
                    target = node.module or ""
                names.add(target)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return names

    def test_modules_only_import_downwards(self):
        checked = 0
        for path in self.ROOT.rglob("*.py"):
            module = self._module_name(path)
            owner = next(
                (
                    prefix
                    for prefix in self.ALLOWED
                    if module == prefix or module.startswith(f"{prefix}.")
                ),
                None,
            )
            if owner is None:
                continue
            checked += 1
            allowed = self.ALLOWED[owner] | self.LEAVES
            for target in self._imports(path):
                if not target.startswith("gsrs."):
                    continue
                if any(
                    target == prefix or target.startswith(f"{prefix}.")
                    for prefix in allowed
                ):
                    continue
                if target == owner or target.startswith(f"{owner}."):
                    continue
                with self.subTest(module=module, imports=target):
                    self.fail(f"{module} must not import {target}")
        self.assertGreater(checked, 10)

    def test_transport_and_responses_have_no_project_dependencies(self):
        for package in ("transport", "responses"):
            for path in (self.ROOT / package).rglob("*.py"):
                module = self._module_name(path)
                for target in self._imports(path):
                    with self.subTest(module=module, imports=target):
                        self.assertFalse(
                            target.startswith("gsrs.")
                            and not target.startswith(f"gsrs.{package}")
                            and target not in self.LEAVES,
                            f"{module} must not import {target}",
                        )

    def test_auth_package_is_importable_without_datasources(self):
        self.assertNotIn("gsrs.datasources", self._imports(self.ROOT / "auth" / "oauth2.py"))


if __name__ == "__main__":
    unittest.main()

