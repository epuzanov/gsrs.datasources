import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gsrs.datasources import Base, Db


class MinimalDatasource(Base):
    """Concrete :class:`Base` implementing the abstract contract."""

    def close(self) -> None:
        return None

    def get(self, id, version=None):
        return None

    def search(self, query=None):
        return []

    def iterate(self, query=None):
        if False:
            yield None

    def save(self, obj):
        return obj

    def validate(self, obj):
        return {"valid": True, "payload": obj}

    def approve(self, id):
        return None


class TypedModel:
    """Stand-in for a ``gsrs.model`` class."""

    @classmethod
    def _resource_path(cls):
        return "substances"

    @classmethod
    def _id_field(cls):
        return "uuid"

    @classmethod
    def model_validate(cls, payload):
        return (cls, payload)


class UntypedModel:
    """A model class without the ``gsrs.model`` path/id hooks."""


class BaseContractTests(unittest.TestCase):
    def test_base_is_abstract(self):
        with self.assertRaises(TypeError):
            Base()

    def test_base_cannot_be_instantiated_with_a_resource_type(self):
        # ``Base`` declares abstract methods, so passing a resource type does
        # not make it instantiable.
        with self.assertRaises(TypeError):
            Base(resource_type=TypedModel)

    def test_raw_mode_uses_empty_resource_path(self):
        datasource = MinimalDatasource()

        self.assertIsNone(datasource.resource_type)
        self.assertIsNone(datasource.id_field)
        self.assertEqual(datasource.resource_path, "")

        payload = {"a": 1}
        self.assertIs(datasource._cast_payload(payload), payload)

    def test_resource_type_derives_path_and_id_field(self):
        datasource = MinimalDatasource(resource_type=TypedModel)

        self.assertIs(datasource.resource_type, TypedModel)
        self.assertEqual(datasource.resource_path, "substances")
        self.assertEqual(datasource.id_field, "uuid")
        self.assertEqual(
            datasource._cast_payload({"a": 1}),
            (TypedModel, {"a": 1}),
        )

    def test_resource_type_without_hooks_falls_back_to_raw_mode(self):
        datasource = MinimalDatasource(resource_type=UntypedModel)

        self.assertIs(datasource.resource_type, UntypedModel)
        self.assertEqual(datasource.resource_path, "")
        self.assertIsNone(datasource.id_field)

    def test_explicit_resource_path_and_id_field_win(self):
        datasource = MinimalDatasource(
            resource_type=TypedModel,
            resource_path="/products/",
            id_field="id",
        )

        self.assertEqual(datasource.resource_path, "products")
        self.assertEqual(datasource.id_field, "id")

    def test_cast_payload_returns_none_unchanged(self):
        datasource = MinimalDatasource(resource_type=TypedModel)

        self.assertIsNone(datasource._cast_payload(None))

    def test_db_stub_close_is_idempotent(self):
        datasource = Db(resource_type=TypedModel)

        datasource.close()
        datasource.close()

        self.assertTrue(datasource._closed)

    def test_db_stub_methods_exist(self):
        datasource = Db(resource_type=TypedModel)

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
        with self.assertRaises(NotImplementedError):
            datasource.approve("abc")


if __name__ == "__main__":
    unittest.main()
