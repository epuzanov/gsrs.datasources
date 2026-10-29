"""OPSIN client and MOL conversion helpers.

`OPSIN <https://www.ebi.ac.uk/opsin/>`_ resolves a systematic IUPAC name to a
chemical structure. It is not a record store: a name either parses or it does
not, and there is no identifier to fetch, no pagination and nothing to write
back. :class:`Opsin` therefore implements ``get`` and ``search`` and models the
name itself as the identifier.

The client speaks the documented `web service
<https://www.ebi.ac.uk/opsin/#webservice>`_: the base URL is
``https://www.ebi.ac.uk/opsin/ws`` and a lookup is a ``GET`` to
``{base}/{CHEMICAL_NAME}.{EXTENSION}``. The name must be URL-encoded and is read
as a single path segment, so slashes are removed and ``+`` is escaped rather
than sent as a space. The documented extensions are ``.smi`` (a SMILES string),
``.cml`` and ``.no2d.cml`` (CML with and without 2D coordinates), ``.stdinchi``,
``.stdinchikey`` and ``.inchi`` (a standard InChI or InChIKey, or a non-standard
tautomer-specific InChI), ``.png`` and ``.svg`` (depictions), and ``.json``.

``.json`` returns ``status``, ``message``, ``cml``, ``inchi``, ``stdinchi``,
``stdinchikey`` and ``smiles``, plus ``warnings`` where applicable. A name that
cannot be parsed answers ``status`` ``FAILURE`` with an explanatory ``message``
instead of a structure. There is no MOL output in the extension list, so the
client asks for ``.json`` and converts its ``cml`` member locally: CML carries
full 2D coordinates together with element types and bond orders, which is
everything a V2000 connection table needs. That CML already lists every atom,
hydrogens included, so :func:`cml_to_molfile` is a direct transcription.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from gsrs.exceptions import ApiResponseError, ClientError

from .http import Http

__all__ = ["Opsin", "OpsinParseError", "cml_to_molfile"]

#: Tag carried by the reference that releases the generated name and structure.
PUBLIC_DOMAIN_TAG = "PUBLIC_DOMAIN_RELEASE"

#: Name type used for a systematic IUPAC name (see ``Name._NAME_TYPE_LABELS``).
SYSTEMATIC_NAME_TYPE = "sys"

#: MOL bond orders, indexed by CML ``order``.
_BOND_ORDERS = {"S": 1, "D": 2, "T": 3, "A": 4}

#: CML bond orders that have no MOL equivalent and are always written as single.
_UNMAPPED_BOND_ORDER = 1

#: Hydrogen isotope symbols, mapped to the MOL mass difference field.
_HYDROGEN_ISOTOPES = {"H": 0, "D": 1, "T": 2}

#: Status OPSIN reports when it could interpret the name.
_SUCCESS_STATUS = "SUCCESS"


class OpsinParseError(ClientError):
    """Raised when OPSIN cannot interpret the supplied name."""


def _local_name(tag: str) -> str:
    """Strip the CML namespace from ``tag``."""
    return tag.rpartition("}")[2]


def _molecule_of(root: ElementTree.Element) -> ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == "molecule":
            return element
    return None


def cml_to_molfile(cml: str) -> str:
    """Convert an OPSIN CML document to a V2000 MOL block.

    ``cml`` is the OPSIN ``.cml`` payload. Coordinates come from ``x2``/``y2``,
    bonds from ``atomRefs2`` plus ``order`` and charges from ``formalCharge``.
    Implicit hydrogens are expanded, so ``C(C)(=O)O`` is written as the acetic
    acid connection table a MOL reader expects rather than as a skeleton.

    Raises :class:`ApiResponseError` when the document has no molecule or no
    atoms, or when it is not XML at all.
    """
    if not cml or not cml.strip():
        raise ApiResponseError("OPSIN returned an empty CML document.")
    try:
        root = ElementTree.fromstring(cml)
    except ElementTree.ParseError as exc:
        raise ApiResponseError("OPSIN returned a malformed CML document.") from exc

    molecule = _molecule_of(root)
    if molecule is None:
        raise ApiResponseError("OPSIN CML document contains no molecule.")

    atom_elements = [
        element for element in molecule.iter() if _local_name(element.tag) == "atom"
    ]
    if not atom_elements:
        raise ApiResponseError("OPSIN CML document contains no atoms.")

    # CML orders atoms by document position, and bonds reference them by ``id``.
    atoms: list[dict[str, Any]] = []
    index_by_id: dict[str, int] = {}
    for element in atom_elements:
        atom_id = element.get("id")
        if not atom_id:
            continue
        symbol = element.get("elementType") or "C"
        mass_difference = 0
        if symbol in _HYDROGEN_ISOTOPES:
            mass_difference = _HYDROGEN_ISOTOPES[symbol]
            symbol = "H"
        index_by_id[atom_id] = len(atoms) + 1
        atoms.append(
            {
                "symbol": symbol,
                "x": float(element.get("x2") or 0.0),
                "y": float(element.get("y2") or 0.0),
                "z": float(element.get("z2") or 0.0),
                "charge": int(element.get("formalCharge") or 0),
                "mass_difference": mass_difference,
            }
        )

    bonds: list[tuple[int, int, int]] = []
    for element in molecule.iter():
        if _local_name(element.tag) != "bond":
            continue
        references = (element.get("atomRefs2") or "").split()
        if len(references) != 2:
            continue
        source, target = (index_by_id.get(reference) for reference in references)
        if source is None or target is None:
            continue
        order = _BOND_ORDERS.get(element.get("order") or "S", _UNMAPPED_BOND_ORDER)
        bonds.append((source, target, order))

    # V2000 atom line: x/y/z, symbol, mass difference, charge, then the stereo,
    # valence, mapping and flag fields this conversion does not use.
    rows = [
        "{:>10.4f}{:>10.4f}{:>10.4f} {:<3}{:>2}{:>3}{:>3}{:>3}{:>3}{:>3}{:>3}{:>3}"
        "{:>3}{:>3}{:>3}{:>3}".format(
            atom["x"],
            atom["y"],
            atom["z"],
            atom["symbol"],
            atom["mass_difference"],
            atom["charge"],
            *[0] * 11,
        )
        for atom in atoms
    ]

    # V2000 bond line: first atom, second atom, bond type, bond stereo.
    bond_rows = [
        "{:>3}{:>3}{:>3}{:>3}".format(source, target, order, 0)
        for source, target, order in bonds
    ]

    table = [
        "",
        "  OPSIN",
        "",
        "{:>3}{:>3}  0  0  0  0  0  0  0  0999 V2000".format(len(atoms), len(bonds)),
        *rows,
        *bond_rows,
        "M  END",
    ]
    return "\n".join(table) + "\n"


class Opsin(Http):
    """Client for the OPSIN IUPAC name resolver.

    A name is the identifier: :meth:`get` returns the public substance a name
    resolves to and :meth:`search` returns the name when it resolves. Payloads
    are cast to ``resource_type`` exactly as in :class:`~gsrs.client.Base`, so
    :meth:`get` returns a plain ``dict`` unless a model class was supplied.
    OPSIN is read-only, so ``iterate``, ``save``, ``validate`` and ``approve``
    raise :class:`NotImplementedError`.

    The returned substance is public at every level: an empty ``access`` list on
    the substance and on the structure, a ``PUBLIC_DOMAIN_RELEASE`` reference
    that both carry, and a name of the requested IUPAC string.
    """

    BASE_URL = "https://www.ebi.ac.uk/opsin"
    NOT_IMPLEMENTED_MESSAGE = "OPSIN is a read-only name resolver."
    WEBSERVICE_PATH = "ws"

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        resource_type: type | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(base_url, resource_type=resource_type, **kwargs)

    def _webservice_url(self, name: str, *, suffix: str = "") -> str:
        """Build the ``ws`` URL for ``name``.

        OPSIN reads the name as one path segment, so slashes are dropped and
        ``quote`` escapes ``+`` and ``?``; without that a name containing them
        would silently change the request.
        """
        encoded = quote(name.strip().replace("/", ""), safe="")
        if not encoded:
            raise ValueError("OPSIN requires a non-empty name.")
        return f"{self.base_url}/{self.WEBSERVICE_PATH}/{encoded}{suffix}"

    @staticmethod
    def _message_of(response: Any) -> str:
        """Extract OPSIN's ``message`` from a JSON failure body."""
        text = getattr(response, "text", "") or ""
        if not text.startswith("{"):
            return ""
        try:
            payload = json.loads(text)
        except ValueError:
            return ""
        return str(payload.get("message") or "") if isinstance(payload, dict) else ""

    def _resolve(self, name: str) -> dict[str, Any] | None:
        """Return the OPSIN JSON result for ``name``, or ``None`` if unknown."""
        if self._closed:
            raise ClientError("Client is closed.")
        url = self._webservice_url(name, suffix=".json")
        response = self._request("GET", url)
        text = response.text or ""
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise OpsinParseError(self._message_of(response) or f"OPSIN returned {response.status_code}.")
        payload = self._parse_json(text, response.url)
        if payload.get("status") != _SUCCESS_STATUS:
            return None
        return payload

    @staticmethod
    def _parse_json(text: str, url: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise ApiResponseError(f"Expected JSON response from {url}.") from exc
        if not isinstance(payload, dict):
            raise ApiResponseError(f"Expected a JSON object from {url}.")
        return payload

    @staticmethod
    def _warnings_of(result: dict[str, Any]) -> list[str]:
        """Return the documented ``warnings`` entries as a list of messages.

        OPSIN omits the key when there is nothing to report and may emit either a
        single string or a list, so both shapes are normalised here.
        """
        warnings = result.get("warnings")
        if not warnings:
            return []
        if isinstance(warnings, str):
            return [warnings]
        return [str(warning) for warning in warnings if warning]

    def _build_substance(self, name: str, result: dict[str, Any]) -> dict[str, Any]:
        """Build the public substance payload described by the request."""
        cml = result.get("cml") or ""
        molfile = cml_to_molfile(cml)

        reference_id = str(uuid4())
        reference = {
            "id": reference_id,
            "citation": "OPSIN",
            "url": self._webservice_url(name, suffix=".cml"),
            "publicDomain": True,
            "tags": [PUBLIC_DOMAIN_TAG],
            "access": [],
        }
        structure = {
            "molfile": molfile,
            "smiles": result.get("smiles"),
            "_inchi": result.get("stdinchi") or result.get("inchi"),
            "_inchiKey": result.get("stdinchikey"),
            "access": [],
            "references": [reference_id],
        }
        payload: dict[str, Any] = {
            "substanceClass": "chemical",
            "access": [],
            "names": [
                {
                    "name": name,
                    "type": SYSTEMATIC_NAME_TYPE,
                    "access": [],
                    "references": [reference_id],
                }
            ],
            "references": [reference],
            "structure": structure,
            # OPSIN resolves a single connected name, so the substance is one
            # moiety carrying the same public structure.
            "moieties": [
                {
                    "molfile": molfile,
                    "smiles": result.get("smiles"),
                    "access": [],
                    "references": [reference_id],
                }
            ],
        }
        # OPSIN's documented ``warnings`` key explains anything it resolved
        # loosely. Notes are public for the same reason as the rest of the
        # payload, and are only sent when there is something to report.
        warnings = self._warnings_of(result)
        if warnings:
            payload["notes"] = [
                {"note": warning, "access": [], "references": [reference_id]}
                for warning in warnings
            ]
        return payload

    def get(self, id: str, version: str | None = None) -> Any:
        """Resolve the IUPAC name ``id`` to a public substance payload.

        The payload is a ``dict`` unless a ``resource_type`` was supplied, in
        which case it is cast to that model. Returns ``None`` when OPSIN cannot
        interpret the name. ``version`` is accepted for compatibility with
        :class:`~gsrs.client.Base` and ignored because OPSIN keeps no record
        history.
        """
        if self._closed:
            raise ClientError("Client is closed.")
        result = self._resolve(id)
        if result is None:
            return None
        return self._cast_payload(self._build_substance(id, result))

    def search(self, query: str | None = None) -> list[str]:
        """Return ``query`` when OPSIN resolves it, otherwise an empty list."""
        if not query:
            return []
        return [query] if self._resolve(query) is not None else []

    def iterate(self, query: str | None = None) -> Any:
        raise NotImplementedError(self.NOT_IMPLEMENTED_MESSAGE)

    def save(self, obj: Any) -> Any:
        raise NotImplementedError(self.NOT_IMPLEMENTED_MESSAGE)

    def validate(self, obj: Any) -> Any:
        raise NotImplementedError(self.NOT_IMPLEMENTED_MESSAGE)

    def approve(self, id: str) -> Any:
        raise NotImplementedError(self.NOT_IMPLEMENTED_MESSAGE)
