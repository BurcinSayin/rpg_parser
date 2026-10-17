import json
import re
from typing import Any

from rpg_parser.core.ports import RawDocument

# Fallback attribution if a record arrives without its embedded `document` block.
# The 5e SRD is CC-BY-4.0, which requires crediting the title, source, and license.
DEFAULT_ATTRIBUTION = (
    "D&D 5e System Reference Document 5.2 © Wizards of the Coast, "
    "via Open5e (https://api.open5e.com), licensed under CC-BY-4.0"
)


def _derive_spell_id(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _components(spell: dict[str, Any]) -> str:
    """Build the classic "V, S, M (...)" components string from Open5e v2 flags.

    Open5e v2 has no `components` list; it exposes boolean verbal/somatic/material
    flags plus an optional `material_specified` description.
    """
    parts = []
    if spell.get("verbal"):
        parts.append("V")
    if spell.get("somatic"):
        parts.append("S")
    if spell.get("material"):
        material = "M"
        specified = spell.get("material_specified")
        if specified:
            material = f"M ({specified})"
        parts.append(material)
    return ", ".join(parts)


def _range(spell: dict[str, Any]) -> str | None:
    range_text = spell.get("range_text")
    if isinstance(range_text, str):
        range_text = range_text.strip()
    if range_text:
        return str(range_text)

    raw_range = spell.get("range")
    if raw_range is None or isinstance(raw_range, bool):
        return None
    value = str(raw_range).strip()
    if not value:
        return None

    unit = spell.get("range_unit")
    if isinstance(unit, str):
        unit = unit.strip()
    if unit:
        return f"{value} {unit}"
    return value


def _attribution(spell: dict[str, Any]) -> str:
    document = spell.get("document") or {}
    title = document.get("name")
    publisher = (document.get("publisher") or {}).get("name")
    if not title:
        return DEFAULT_ATTRIBUTION
    credit = f"{title} © {publisher}" if publisher else title
    return f"{credit}, via Open5e (https://api.open5e.com), licensed under CC-BY-4.0"


class Dnd5eOpen5eSpellParser:
    """Maps a single Open5e v2 spell JSON object to the project's spell dict shape."""

    def parse(self, document: RawDocument) -> dict[str, Any]:
        spell = json.loads(document.content)

        name = spell.get("name") or ""
        spell_data: dict[str, Any] = {
            "id": _derive_spell_id(name),
            "Name": name,
            "Level": spell.get("level"),
            "School": (spell.get("school") or {}).get("name"),
            "Casting Time": spell.get("casting_time"),
            "Range": _range(spell),
            "Components": _components(spell),
            "Duration": spell.get("duration"),
            "Ritual": bool(spell.get("ritual")),
            "Concentration": bool(spell.get("concentration")),
            "Classes": [c.get("name") for c in (spell.get("classes") or []) if c.get("name")],
            "Description": spell.get("desc") or "",
        }

        material = spell.get("material_specified")
        if material:
            spell_data["Material"] = material

        higher_level = spell.get("higher_level")
        if higher_level:
            spell_data["Higher Levels"] = higher_level

        spell_data["Source"] = _attribution(spell)
        # Preserve the upstream key for traceability back to Open5e.
        if spell.get("key"):
            spell_data["key"] = spell["key"]

        return spell_data
