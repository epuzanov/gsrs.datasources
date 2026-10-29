import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gsrs.client.opsin import Opsin, OpsinParseError, cml_to_molfile

BENZENE_CML = """<?xml version="1.0" encoding="UTF-8"?>
<cml xmlns="http://www.xml-cml.org/schema" convention="conventions:molecular">
  <molecule id="m1">
    <name dictRef="nameDict:unknown">benzene</name>
    <atomArray>
      <atom id="a1" elementType="C" hydrogenCount="0" x2="0.0000" y2="0.0000"/>
      <atom id="a2" elementType="C" x2="-1.0000" y2="0.0000"/>
      <atom id="a3" elementType="H" x2="0.5000" y2="0.8660"/>
      <atom id="a4" elementType="O" formalCharge="-1" x2="-1.5000" y2="0.8660"/>
    </atomArray>
    <bondArray>
      <bond id="a1_a2" atomRefs2="a1 a2" order="D"/>
      <bond id="a1_a3" atomRefs2="a1 a3" order="S"/>
      <bond id="a2_a4" atomRefs2="a2 a4" order="T"/>
    </bondArray>
  </molecule>
</cml>
"""

OPSIN_SUCCESS = {
    "status": "SUCCESS",
    "message": "",
    "cml": BENZENE_CML,
    "inchi": "InChI=1S/C6H6/c1-2-4-6-5-3-1/h1-6H",
    "stdinchi": "InChI=1S/C6H6/c1-2-4-6-5-3-1/h1-6H",
    "stdinchikey": "UHOVQNZJYSORNB-UHFFFAOYSA-N",
    "smiles": "c1ccccc1",
}

OPSIN_FAILURE = {
    "status": "FAILURE",
    "message": "aspirin was uninterpretable due to the following section of the name: asp",
}

OPSIN_WARNED = dict(OPSIN_SUCCESS, warnings="Accepted 'benzene' as an aromatic ring")

OPSIN_WARNED_MANY = dict(
    OPSIN_SUCCESS,
    warnings=["first warning", "second warning"],
)


class FakeResponse:
    def __init__(self, payload, status_code=200, url="https://www.ebi.ac.uk/opsin/ws/benzene.json"):
        self._payload = payload
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        self.text = payload if isinstance(payload, str) else json.dumps(payload)


class FakeSession:
    """Routes OPSIN requests to a handler and records every call."""

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
        return self._handler(method, url, headers=headers or {})

    def close(self):
        self.close_calls += 1


def opsin_session(result=OPSIN_SUCCESS, status_code=200):
    """Session returning ``result`` for every OPSIN name lookup."""
    return FakeSession(
        lambda method, url, **kwargs: FakeResponse(result, status_code=status_code, url=url)
    )


class FakeSubstance:
    """Minimal stand-in for ``gsrs.model.ChemicalSubstance``."""

    def __init__(self, payload):
        self.payload = payload
        self.access = payload.get("access")
        self.names = payload.get("names")
        self.references = payload.get("references")
        self.structure = payload.get("structure")
        self.moieties = payload.get("moieties")

    @classmethod
    def model_validate(cls, payload):
        return cls(payload)


class CmlToMolfileTests(unittest.TestCase):
    def test_writes_a_v2000_header_and_counts_line(self):
        molfile = cml_to_molfile(BENZENE_CML)
        lines = molfile.splitlines()

        self.assertEqual(lines[3], "  4  3  0  0  0  0  0  0  0  0999 V2000")
        self.assertTrue(molfile.endswith("M  END\n"))

    def test_maps_bond_orders(self):
        molfile = cml_to_molfile(BENZENE_CML)
        bond_rows = [line for line in molfile.splitlines() if len(line) == 12 and "  " in line]

        self.assertIn("  1  2  2  0", molfile)
        self.assertIn("  1  3  1  0", molfile)
        self.assertIn("  2  4  3  0", molfile)
        self.assertTrue(bond_rows)

    def test_keeps_coordinates_charge_and_elements(self):
        molfile = cml_to_molfile(BENZENE_CML)
        atom_rows = molfile.splitlines()[4:8]

        self.assertEqual(len(atom_rows), 4)
        self.assertIn(" C ", atom_rows[0])
        self.assertIn(" H ", atom_rows[2])
        self.assertIn(" O ", atom_rows[3])
        # V2000 field offsets: symbol 31:34, mass difference 34:36, charge 36:39.
        self.assertEqual(atom_rows[3][36:39].strip(), "-1")
        # x2 coordinates are preserved to four decimals.
        self.assertEqual(atom_rows[1][:10].strip(), "-1.0000")

    def test_maps_deuterium_to_a_hydrogen_mass_difference(self):
        cml = BENZENE_CML.replace('elementType="H"', 'elementType="D"')

        molfile = cml_to_molfile(cml)
        row = molfile.splitlines()[6]

        self.assertEqual(row[31:34].strip(), "H")
        self.assertEqual(row[34:36].strip(), "1")

    def test_rejects_an_empty_document(self):
        with self.assertRaises(Exception):
            cml_to_molfile("")

    def test_rejects_malformed_xml(self):
        with self.assertRaises(Exception):
            cml_to_molfile("<cml><molecule>")

    def test_rejects_a_document_without_atoms(self):
        with self.assertRaises(Exception):
            cml_to_molfile("<cml><molecule id='m1'><atomArray/></molecule></cml>")


class OpsinClientTests(unittest.TestCase):
    def test_uses_the_webservice_path(self):
        session = opsin_session()
        client = Opsin(session=session)

        client.get("benzene")

        self.assertEqual(
            session.calls[0]["url"], "https://www.ebi.ac.uk/opsin/ws/benzene.json"
        )

    def test_encodes_names_as_a_single_path_segment(self):
        session = opsin_session()
        client = Opsin(session=session)

        client.get("2-acetoxybenzoic acid")

        url = urlparse(session.calls[0]["url"])
        self.assertEqual(url.path, "/opsin/ws/2-acetoxybenzoic%20acid.json")

    def test_escapes_plus_and_slash_in_names(self):
        session = opsin_session()
        client = Opsin(session=session)

        client.get("a+b/c")

        # ``+`` must not survive as a space and ``/`` must not add a segment.
        self.assertEqual(session.calls[0]["url"], "https://www.ebi.ac.uk/opsin/ws/a%2Bbc.json")

    def test_get_returns_the_resolved_substance(self):
        client = Opsin(session=opsin_session(), resource_type=FakeSubstance)

        substance = client.get("benzene")

        self.assertIsInstance(substance, FakeSubstance)
        self.assertEqual(substance.names[0]["name"], "benzene")
        self.assertEqual(substance.names[0]["type"], "sys")
        self.assertIn(" V2000", substance.structure["molfile"])
        self.assertEqual(substance.structure["smiles"], "c1ccccc1")
        self.assertEqual(substance.structure["_inchiKey"], "UHOVQNZJYSORNB-UHFFFAOYSA-N")

    def test_get_returns_a_public_substance(self):
        client = Opsin(session=opsin_session(), resource_type=FakeSubstance)

        substance = client.get("benzene")

        self.assertEqual(substance.access, [])
        self.assertEqual(substance.structure["access"], [])
        self.assertEqual(substance.moieties[0]["access"], [])

    def test_get_omits_notes_without_warnings(self):
        client = Opsin(session=opsin_session(), resource_type=FakeSubstance)

        self.assertNotIn("notes", client.get("benzene").payload)

    def test_get_reports_warnings_as_public_notes(self):
        client = Opsin(session=opsin_session(OPSIN_WARNED), resource_type=FakeSubstance)

        notes = client.get("benzene").payload["notes"]

        self.assertEqual([note["note"] for note in notes], [OPSIN_WARNED["warnings"]])
        self.assertEqual(notes[0]["access"], [])

    def test_get_reports_every_warning_in_a_list(self):
        client = Opsin(session=opsin_session(OPSIN_WARNED_MANY), resource_type=FakeSubstance)

        notes = client.get("benzene").payload["notes"]

        self.assertEqual(
            [note["note"] for note in notes], ["first warning", "second warning"]
        )

    def test_get_attaches_a_public_domain_release_reference(self):
        client = Opsin(session=opsin_session(), resource_type=FakeSubstance)

        substance = client.get("benzene")
        reference = substance.references[0]

        self.assertTrue(reference["publicDomain"])
        self.assertEqual(reference["tags"], ["PUBLIC_DOMAIN_RELEASE"])
        self.assertEqual(reference["access"], [])
        # The name and the structure both cite the released record.
        self.assertEqual(substance.names[0]["references"], [reference["id"]])
        self.assertEqual(substance.structure["references"], [reference["id"]])

    def test_get_returns_none_for_an_uninterpretable_name(self):
        client = Opsin(session=opsin_session(OPSIN_FAILURE, status_code=404))

        self.assertIsNone(client.get("aspirin"))

    def test_get_returns_none_when_opsin_reports_failure(self):
        client = Opsin(session=opsin_session(OPSIN_FAILURE, status_code=200))

        self.assertIsNone(client.get("aspirin"))

    def test_get_returns_a_dict_without_a_resource_type(self):
        client = Opsin(session=opsin_session())

        payload = client.get("benzene")

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["substanceClass"], "chemical")

    def test_get_casts_when_a_resource_type_is_supplied(self):
        client = Opsin(session=opsin_session(), resource_type=FakeSubstance)

        self.assertIsInstance(client.get("benzene"), FakeSubstance)

    def test_ignores_the_version_argument(self):
        session = opsin_session()
        client = Opsin(session=session)

        client.get("benzene", version="2")

        self.assertEqual(len(session.calls), 1)

    def test_search_returns_the_name_when_it_resolves(self):
        client = Opsin(session=opsin_session())

        self.assertEqual(client.search("benzene"), ["benzene"])

    def test_search_returns_nothing_when_the_name_does_not_resolve(self):
        client = Opsin(session=opsin_session(OPSIN_FAILURE, status_code=404))

        self.assertEqual(client.search("aspirin"), [])

    def test_search_without_a_query_skips_the_network(self):
        session = opsin_session()
        client = Opsin(session=session)

        self.assertEqual(client.search(), [])
        self.assertEqual(client.search(""), [])
        self.assertEqual(session.calls, [])

    def test_raises_for_an_unexpected_status(self):
        client = Opsin(session=opsin_session({"status": "ERROR", "message": "boom"}, status_code=500))

        with self.assertRaises(OpsinParseError):
            client.get("benzene")

    def test_raises_for_a_non_json_body(self):
        client = Opsin(session=opsin_session("<html>nope</html>", status_code=200))

        with self.assertRaises(Exception):
            client.get("benzene")

    def test_rejects_an_empty_name(self):
        client = Opsin(session=opsin_session())

        with self.assertRaises(ValueError):
            client.get("   ")

    def test_raises_once_closed(self):
        client = Opsin(session=opsin_session())
        client.close()

        with self.assertRaises(Exception):
            client.get("benzene")

    def test_close_is_idempotent(self):
        session = opsin_session()
        client = Opsin(session=session)

        client.close()
        client.close()

        # A caller supplied session owns its own resources.
        self.assertEqual(session.close_calls, 0)

    def test_read_only_operations_are_unimplemented(self):
        client = Opsin(session=opsin_session())

        for call in (
            lambda: client.iterate("benzene"),
            lambda: client.save({}),
            lambda: client.validate({}),
            lambda: client.approve("benzene"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(NotImplementedError):
                    call()

    def test_satisfies_the_base_contract(self):
        from gsrs.client import Base

        self.assertTrue(issubclass(Opsin, Base))
        self.assertFalse(Opsin.__abstractmethods__)


if __name__ == "__main__":
    unittest.main()
