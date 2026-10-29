# gsrs.datasources

`gsrs.datasources` provides datasource implementations for the `gsrs` Python
namespace package.

## What is included

- `Gsrs`: a GSRS API datasource with search, iteration, fetch, validate, and save helpers.
- `Http`: a reusable HTTP datasource base built on the Python standard library.
- `AuthHandler`, `BasicAuthHandler`, `BearerAuthHandler`, `LegacyAuthHandler`,
  and `OAuth2AuthHandler`: urllib request handlers for static headers, HTTP
  Basic credentials stored in an `HTTPPasswordMgr`, static bearer tokens, GSRS
  legacy headers, and OAuth2 bearer tokens.
- `SsoHeaderAuthHandler`, `SessionCookieAuthHandler`, `LegacyAuthHandler`,
  `TokenAuthHandler`, `ComputedTokenAuthHandler`, and `ApiKeyAuthHandler`:
  handlers for every GSRS authentication method (SSO trust headers, `ix.session`
  cookie, username/password, `auth-token`, and `auth-key`).
- `compute_gsrs_token`: helper that derives a GSRS `auth-token` from a username
  and API key.
- `OAuth2Token`: an OAuth2 bearer token provider with caching and automatic refresh.
- `Db`: a placeholder database datasource stub for future implementation.
- `ValidationResponse`, `ValidationMessage`, and `ValidationLink`: pydantic models for GSRS validation output.

`resourceType` is a `gsrs.model` class, and it controls both the endpoint the
datasource talks to and the type it returns: `Gsrs(resourceType=Substance, ...)`
requests `/substances` and casts every payload to `gsrs.model.Substance`.
Passing `resourceType=None` (the default) selects raw mode, where records come
back as plain dictionaries and requests are resolved directly against
`base_url` with no entity segment. The lowercase `resource_type` argument is
accepted as well; both spellings are equivalent.

The implementation also supports GSRS-specific API conventions documented by
the GSRS project, including JSON views and legacy `auth-username` /
`auth-password` header-based authentication. Views are not exposed as a
datasource argument: each operation picks the view GSRS requires (`key` for
`search`, `full` for `get` and `iterate`), and `save`, `validate`, and `approve`
send no view at all.

Both `Http` and `Gsrs` accept a single `auth` parameter containing an
`AuthHandler`. HTTP Basic and GSRS legacy credentials are kept in an
`HTTPPasswordMgr` and sent by `BasicAuthHandler` and `LegacyAuthHandler`;
static bearer tokens are sent by `BearerAuthHandler`, arbitrary headers by
`AuthHandler`, OAuth2 bearer tokens are handled by `OAuth2AuthHandler`, an
`AbstractBasicAuthHandler` subclass backed by `OAuth2Token`, and the remaining
GSRS methods (SSO trust headers, `ix.session` cookie, `auth-token`, and
`auth-key`) by the handlers described in
[GSRS authentication methods](#gsrs-authentication-methods). Tokens are cached,
refreshed automatically when they expire, and renewed once when an API request
is answered with `401 Unauthorized`.

The code is split into packages by layer, and each dependency points strictly
downwards. Every package is decomposed into one module per concern:

| Package | Modules | Contents |
| --- | --- | --- |
| `gsrs.transport` | `proxy`, `tls`, `headers`, `handlers`, `opener` | Lowest layer: proxy and `no_proxy` normalization, TLS context creation, response-header helpers, the `urllib` handler subclasses, and opener construction. Imports nothing else from the project. |
| `gsrs.responses` | `http`, `whoami`, `validation` | Data containers: the transport-level `HttpResponse` plus the pydantic GSRS API models (`WhoAmIResponse`, `ValidationResponse`, ...). |
| `gsrs.exceptions` | `exceptions` | Dependency-free exception hierarchy (`DatasourceError`, `HttpRequestError`, ...) that any layer may import. |
| `gsrs.auth` | `base`, `tokens`, `basic`, `token_header`, `api_key`, `sso`, `session`, `bearer`, `oauth2` | The GSRS authentication handlers, `compute_gsrs_token`, and the `OAuth2Token` provider. Builds on `transport` and `exceptions`. |
| `gsrs.datasources` | `base`, `http`, `gsrs`, `db` | `Base` (the abstract contract), `Http` (requests and pagination), `Gsrs` (GSRS operations), and the `Db` stub, on top of `auth`, `responses`, and `transport`. |

`gsrs.datasources.http` still re-exports the public names it builds on, so
imports such as `from gsrs.datasources.http import AuthHandler` keep working.
In application code, import from `gsrs.datasources`.


## Installation

Install the package:

```bash
pip install gsrs-datasources
```

Install the companion `gsrs.model` package in the same environment before using
`Gsrs`.

Install it in editable mode for local development:

```bash
pip install -e .
```

## Usage

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, LegacyAuthHandler, ValidationResponse

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=LegacyAuthHandler("username", "password"),
)

identifiers = datasource.search("name:aspirin")
substance = datasource.get(identifiers[0])
validation: ValidationResponse = datasource.validate(substance)

for substance in datasource.iterate("name:aspirin"):
    print(substance)

datasource.close()
```

`substance` above is hydrated through `gsrs.model.Substance`, and `validation`
is a typed GSRS validation response with structured `messages`.

Use a second datasource when you want the untyped API payload:

```python
raw_datasource = Gsrs(
    base_url="https://example.test/api/v1",
    auth=LegacyAuthHandler("username", "password"),
)

raw_record = raw_datasource.get(identifiers[0])
```

`raw_record` is the plain dictionary returned by the API; `get`, `iterate`,
`save`, and `approve` all return raw JSON in this mode.

## Authentication

Authentication is configured with a single `auth` parameter. It must be an
`AuthHandler` instance, and every supported authentication method is an
`AuthHandler` subclass.

HTTP Basic credentials are stored in an `HTTPPasswordMgr` and sent by
`BasicAuthHandler`:

```python
from gsrs.model import Substance
from gsrs.datasources import BasicAuthHandler, Gsrs

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=BasicAuthHandler("username", "password"),
)
```

GSRS legacy `auth-username` / `auth-password` headers are sent by
`LegacyAuthHandler`:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, LegacyAuthHandler

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=LegacyAuthHandler("username", "password"),
)
```

Use `BearerAuthHandler` when you already have an OAuth2 access token:

```python
from gsrs.model import Substance
from gsrs.datasources import BearerAuthHandler, Gsrs

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=BearerAuthHandler("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."),
)
```

Use `OAuth2AuthHandler` to let the datasource obtain and refresh tokens. The
default `client_credentials` grant authenticates the client with HTTP Basic
auth:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, OAuth2AuthHandler, OAuth2Token

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=OAuth2AuthHandler(
        OAuth2Token(
            token_url="https://example.test/oauth2/token",
            client_id="gsrs-client",
            client_secret="secret",
            scope="gsrs.read gsrs.write",
        )
    ),
)
```

`OAuth2AuthHandler` also accepts a mapping of `OAuth2Token` arguments. The
`password` grant (resource owner password credentials) is available for GSRS
deployments that issue tokens for a user:

```python
datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=OAuth2AuthHandler(
        {
            "token_url": "https://example.test/oauth2/token",
            "client_id": "gsrs-client",
            "client_secret": "secret",
            "grant_type": "password",
            "username": "gsrs-user",
            "password": "gsrs-password",
        }
    ),
)
```

Arbitrary authentication headers can be sent with the base `AuthHandler`:

```python
from gsrs.model import Substance
from gsrs.datasources import AuthHandler, Gsrs

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://example.test/api/v1",
    auth=AuthHandler({"X-API-Key": "secret-key"}),
)
```

`OAuth2Token` also accepts `audience`, `extra_params`, `client_auth` (`basic`
or `body`), `timeout`, and `leeway`. An explicit `Authorization` header always
takes precedence over the configured handler.

### GSRS authentication methods

Besides Basic and OAuth2, the handlers cover every method described in
[the GSRS backend login process](https://github.com/ncats/gsrs3-main-deployment/blob/main/docs/the-backend-login-process.md).
A GSRS server evaluates them in this order, and each method below is
independent: pick the single handler that matches how your deployment
authenticates clients.

1. SSO proxy trust headers
2. `ix.session` session cookie
3. `auth-username` plus `auth-password`
4. `auth-token` (computed token)
5. `auth-key` (API key) plus `auth-username`

#### SSO trust headers

`SsoHeaderAuthHandler` sends the username, and optionally the e-mail and roles,
in the headers your SSO proxy is configured to trust
(`ix.authentication.usernameheader`, `useremailheader`, `userrolesheader`):

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, SsoHeaderAuthHandler

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    auth=SsoHeaderAuthHandler(
        "gsrs-user",
        username_header="OAM_REMOTE_USER",
        email="user@example.test",
        email_header="OAM_REMOTE_EMAIL",
        roles=["Query", "Updater"],
        roles_header="OAM_REMOTE_ROLES",
    ),
)
```

Roles are joined with `;` (GSRS splits them on that separator) unless you pass an
already formatted string, and `roles_separator` changes the separator.

#### Session cookie

`SessionCookieAuthHandler` sends `Cookie: ix.session=<id>`. Pass a known
session id, or pass `credentials` and let the handler log in and capture the
cookie from the `Set-Cookie` response header:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, LegacyAuthHandler, SessionCookieAuthHandler

auth = SessionCookieAuthHandler(credentials=LegacyAuthHandler("user", "secret"))
datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    auth=auth,
)

datasource.whoami()  # logs in and captures ix.session
print(auth.session_id)
datasource.whoami()  # reuses the cookie, credentials stay available as fallback
```

GSRS only creates a session for an already authenticated request, so the
credentials are still sent after the cookie is captured; that way GSRS falls
back to them when the stored session expires. Pass `cookie_name` if the
deployment changed `gsrs.sessions.sessionCookieName`, `capture=False` to keep
the id static, and `session_id` when the session was created elsewhere.

#### Computed token

GSRS does not store tokens: the server derives them as
`sha1(canonicalTimestamp + username + key)`. `ComputedTokenAuthHandler` derives
the token locally from the username and API key (`key` in the `api/v1/whoami`
response), so it keeps working while the canonical timestamp rolls over:

```python
from gsrs.model import Substance
from gsrs.datasources import ComputedTokenAuthHandler, Gsrs

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    auth=ComputedTokenAuthHandler("gsrs-user", "BPwnt6sw8yTSfOqjjhNr"),
)
```

`TokenAuthHandler` sends a token you obtained yourself, for example
`computedToken` from `whoami`. Pass a zero argument callable instead of a string
to refresh short lived tokens per request:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, TokenAuthHandler

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    auth=TokenAuthHandler(lambda: fetch_current_token()),
)
```

Both handlers send `auth-token`; use `header=` to send the token under a
different name. `compute_gsrs_token(username, key)` is exported for callers that
need the token value itself, and `time_resolution_ms` matches
`gsrs.tokens.timeResolutionMS` (default `86400000`, one day).

#### API key

`ApiKeyAuthHandler` sends the long lived API key in `auth-key` along with
`auth-username`, which GSRS uses to look up the user profile:

```python
from gsrs.model import Substance
from gsrs.datasources import ApiKeyAuthHandler, Gsrs

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    auth=ApiKeyAuthHandler("BPwnt6sw8yTSfOqjjhNr", username="gsrs-user"),
)
```

Some legacy examples and proxies use `auth-user` instead of `auth-username`;
set `user_header="auth-user"` for those, or `user_header=None` to send the key
alone.

### Self-signed certificates

`Http`, `Gsrs`, and `OAuth2Token` accept `verify_ssl` (default `True`). Set it to
`False` to accept self-signed or otherwise unverified TLS certificates. Configure
it on the datasource for API requests and on `OAuth2Token` for token requests:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, OAuth2AuthHandler, OAuth2Token

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    verify_ssl=False,
    auth=OAuth2AuthHandler(
        OAuth2Token(
            token_url="https://auth.example.test/oauth2/token",
            client_id="gsrs-client",
            client_secret="secret",
            verify_ssl=False,
        )
    ),
)
```

When you pass your own `session` to a datasource or your own `opener` to
`OAuth2Token`, that object is responsible for its TLS configuration and
`verify_ssl` has no effect.

### Proxy support

`Http`, `Gsrs`, and `OAuth2Token` accept `proxy` and `no_proxy`. `proxy` is
either a proxy URL used for both HTTP and HTTPS, or a mapping of URL scheme to
proxy URL. A proxy URL without a scheme defaults to `http`:

```python
from gsrs.model import Substance
from gsrs.datasources import Gsrs, OAuth2AuthHandler, OAuth2Token

datasource = Gsrs(
    resourceType=Substance,
    base_url="https://gsrs.example.test/api/v1",
    proxy="http://proxy.example.test:3128",
    no_proxy="localhost,.internal.test",
    auth=OAuth2AuthHandler(
        OAuth2Token(
            token_url="https://auth.example.test/oauth2/token",
            client_id="gsrs-client",
            client_secret="secret",
            proxy={"https": "http://proxy.example.test:3128"},
            no_proxy=["localhost", ".internal.test"],
        )
    ),
)
```

`no_proxy` accepts a comma separated string or a sequence of hosts. An entry
matches the host itself and its subdomains, so both `example.test` and
`.example.test` cover `api.example.test`; `*` bypasses the proxy for every host.

When `proxy` is not given, the standard proxy environment variables
(`http_proxy`, `https_proxy`, `no_proxy`, and their uppercase variants) are
used. Configure the proxy on `OAuth2Token` as well when the token endpoint must
also be reached through the proxy. As with `verify_ssl`, a caller supplied
`session` or `opener` is responsible for its own proxy configuration.

## Testing

```bash
python -m unittest discover -s tests -v
```

## License

MIT
