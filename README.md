# gsrs.datasources

`gsrs.datasources` provides datasource implementations for the `gsrs` Python
namespace package.

## What is included

- `Gsrs`: a GSRS API datasource with search, iteration, fetch, validate, and save helpers.
- `Http`: a reusable HTTP datasource base built on the Python standard library.
- `Db`: a placeholder database datasource stub for future implementation.
- `ValidationResponse`, `ValidationMessage`, and `ValidationLink`: pydantic models for GSRS validation output.

`gsrs.model` is required when using `Gsrs`. The datasource hydrates API
payloads into `gsrs.model` objects by default, and `raw=True` returns raw
dictionaries when you explicitly want the API payload.

The implementation also supports GSRS-specific API conventions documented by
the GSRS project, including JSON views (`full`, `compact`, `key`) and legacy
`auth-username` / `auth-password` header-based authentication.

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
from gsrs.datasources import Gsrs, ValidationResponse

datasource = Gsrs(
    resourceType="Substance",
    base_url="https://example.test/api/v1",
    legacy_auth=("username", "password"),
)

identifiers = datasource.search("name:aspirin", page_size=25)
substance = datasource.get(identifiers[0], view=Gsrs.VIEW_COMPACT)
raw_record = datasource.get(identifiers[0], raw=True)
validation: ValidationResponse = datasource.validate(raw_record)

for substance in datasource.iterate("name:aspirin"):
    print(substance)

datasource.close()
```

`substance` above is hydrated through `gsrs.model.Substance`, while
`raw_record` is the untyped API payload. `validation` is a typed GSRS
validation response with structured `messages`.

## Testing

```bash
python -m unittest discover -s tests -v
```

## License

MIT
