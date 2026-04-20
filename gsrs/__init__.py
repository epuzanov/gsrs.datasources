from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

from . import datasources

__all__ = ["datasources", "model"]


def __getattr__(name: str):
    from importlib import import_module

    if name.startswith("__") or name in {
        "load_tests",
        "pytest_plugins",
        "setUpModule",
        "tearDownModule",
    }:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        model = import_module("gsrs.model")
    except ModuleNotFoundError as exc:
        if exc.name == "gsrs.model":
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
        raise

    if name == "model":
        return model

    try:
        return getattr(model, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
