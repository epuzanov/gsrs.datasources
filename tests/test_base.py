import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gsrs.datasources import Base, Db


class MinimalDatasource(Base):
    def close(self) -> None:
        return None

    def get(self, id, version=None, raw=False, template=None):
        return None

    def search(self, query=None, *, page_size=50, params=None, template=None):
        return []

    def iterate(self, query=None, *, raw=False, page_size=50, params=None, template=None):
        if False:
            yield None

    def save(self, obj, update=False):
        return obj

    def validate(self, obj, update=False, *, view=None):
        return {"valid": True, "payload": obj}


class BaseContractTests(unittest.TestCase):
    def test_base_is_abstract(self):
        with self.assertRaises(TypeError):
            Base("Substance")

    def test_extend_returns_object_unchanged(self):
        datasource = MinimalDatasource("Substance")
        payload = {"value": 1}

        self.assertIs(datasource.extend(payload), payload)

    def test_resource_type_is_validated_at_construction(self):
        with self.assertRaisesRegex(ValueError, "Unsupported resourceType"):
            MinimalDatasource("Invalid")

    def test_db_stub_close_is_idempotent(self):
        datasource = Db("Substance")

        datasource.close()
        datasource.close()

        self.assertTrue(datasource._closed)

    def test_db_stub_methods_exist(self):
        datasource = Db("Substance")

        with self.assertRaises(NotImplementedError):
            datasource.get("abc")
        with self.assertRaises(NotImplementedError):
            datasource.search("name:aspirin")
        with self.assertRaises(NotImplementedError):
            next(datasource.iterate())
        with self.assertRaises(NotImplementedError):
            datasource.save({"resourceType": "Substance"})
        with self.assertRaises(NotImplementedError):
            datasource.validate({"resourceType": "Substance"})


if __name__ == "__main__":
    unittest.main()
