import unittest

from postgreslite.pool import TableColumn


class TestTableColumn(unittest.TestCase):
    def _make(self, **kwargs):
        defaults = {"name": "id", "type": "INTEGER", "notnull": False, "default": None, "pk": True}
        defaults.update(kwargs)
        return TableColumn(**defaults)

    def test_repr(self):
        col = self._make(name="age", type="INTEGER", notnull=True, default=None, pk=False)
        self.assertIn("age", repr(col))
        self.assertIn("INTEGER", repr(col))

    def test_from_row(self):
        row = {"name": "x", "type": "TEXT", "notnull": 1, "dflt_value": "hello", "pk": 0}
        col = TableColumn._from_row(row)
        self.assertEqual(col.name, "x")
        self.assertTrue(col.notnull)
        self.assertFalse(col.pk)
        self.assertEqual(col.default, "hello")


if __name__ == "__main__":
    unittest.main()
