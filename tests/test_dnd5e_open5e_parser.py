import json
import unittest
from pathlib import Path

from rpg_parser.adapters.parsers.dnd5e_open5e import Dnd5eOpen5eSpellParser
from rpg_parser.core.ports import RawDocument


class TestDnd5eOpen5eSpellParser(unittest.TestCase):
    def setUp(self):
        self.parser = Dnd5eOpen5eSpellParser()
        samples_dir = Path(__file__).parent.parent / "samples"
        with open(samples_dir / "sample_dnd5e_open5e_spell.json", "r", encoding="utf-8") as f:
            self.spell_json = f.read()

    def _parse(self, content: str) -> dict:
        return self.parser.parse(
            RawDocument(content=content, source="test", media_type="application/json")
        )

    def test_parse_fireball(self):
        result = self._parse(self.spell_json)

        self.assertEqual(result["id"], "fireball")
        self.assertEqual(result["Name"], "Fireball")
        self.assertEqual(result["Level"], 3)
        self.assertEqual(result["School"], "Evocation")
        self.assertEqual(result["Casting Time"], "action")
        self.assertEqual(result["Range"], "150 feet")
        self.assertEqual(result["Components"], "V, S, M (a ball of bat guano and sulfur)")
        self.assertEqual(result["Material"], "a ball of bat guano and sulfur")
        self.assertEqual(result["Duration"], "instantaneous")
        self.assertFalse(result["Ritual"])
        self.assertFalse(result["Concentration"])
        self.assertEqual(result["Classes"], ["Sorcerer", "Wizard"])
        self.assertIn("A bright streak flashes from you", result["Description"])
        self.assertEqual(
            result["Higher Levels"],
            "The damage increases by 1d6 for each spell slot level above 3.",
        )
        self.assertEqual(result["key"], "srd-2024_fireball")

    def test_attribution_is_present(self):
        result = self._parse(self.spell_json)

        self.assertIn("System Reference Document 5.2", result["Source"])
        self.assertIn("Wizards of the Coast", result["Source"])
        self.assertIn("CC-BY-4.0", result["Source"])

    def test_components_built_from_flags(self):
        spell = {
            "name": "Test Spell",
            "verbal": True,
            "somatic": False,
            "material": True,
            "material_specified": "a pinch of dust",
        }
        result = self._parse(json.dumps(spell))
        self.assertEqual(result["Components"], "V, M (a pinch of dust)")

    def test_material_without_specification(self):
        spell = {"name": "Test", "verbal": False, "somatic": True, "material": True}
        result = self._parse(json.dumps(spell))
        self.assertEqual(result["Components"], "S, M")

    def test_missing_optional_fields_are_defensive(self):
        # A near-empty record must not raise; optional keys simply stay absent.
        result = self._parse(json.dumps({"name": "Sparse Spell"}))

        self.assertEqual(result["id"], "sparse-spell")
        self.assertEqual(result["Name"], "Sparse Spell")
        self.assertIsNone(result["Level"])
        self.assertIsNone(result["School"])
        self.assertIsNone(result["Casting Time"])
        self.assertIsNone(result["Range"])
        self.assertIsNone(result["Duration"])
        self.assertEqual(result["Classes"], [])
        self.assertEqual(result["Components"], "")
        self.assertNotIn("Material", result)
        self.assertNotIn("Higher Levels", result)
        # Attribution always falls back even without a document block.
        self.assertIn("CC-BY-4.0", result["Source"])

    def test_range_composes_value_and_unit_when_range_text_missing(self):
        for payload, expected in (
            ({"name": "A", "range_text": "", "range": 150, "range_unit": "feet"}, "150 feet"),
            ({"name": "B", "range_text": None, "range": 60, "range_unit": "feet"}, "60 feet"),
            ({"name": "C", "range": 0, "range_unit": "feet"}, "0 feet"),
            ({"name": "D", "range_text": "", "range": 150, "range_unit": None}, "150"),
            ({"name": "E", "range_text": "", "range": 150, "range_unit": ""}, "150"),
            ({"name": "F", "range_text": "Self", "range": 0, "range_unit": "feet"}, "Self"),
        ):
            with self.subTest(payload=payload):
                result = self._parse(json.dumps(payload))
                self.assertEqual(result["Range"], expected)

    def test_range_is_none_when_both_range_text_and_range_absent(self):
        for payload in (
            {"name": "A", "range_text": None, "range": None, "range_unit": "feet"},
            {"name": "B", "range_text": "", "range": None, "range_unit": "feet"},
            {"name": "C", "range_text": "   ", "range": ""},
            {"name": "D", "range": False, "range_unit": "feet"},
        ):
            with self.subTest(payload=payload):
                result = self._parse(json.dumps(payload))
                self.assertIsNone(result["Range"])


if __name__ == "__main__":
    unittest.main()
