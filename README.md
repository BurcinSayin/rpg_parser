# RPG Parser

[![CI](https://github.com/BurcinSayin/rpg_parser/actions/workflows/ci.yml/badge.svg)](https://github.com/BurcinSayin/rpg_parser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Command-line utility for fetching tabletop RPG spell data — Pathfinder 1e/2e from Archives of Nethys and D&D 5e (SRD) from the Open5e API — and exporting structured JSON.

> **Unofficial fan tool.** This project is not affiliated with, endorsed by, or sponsored by Paizo Inc., Archives of Nethys, Wizards of the Coast, or Open5e. See [License and Legal](#license-and-legal) before scraping or redistributing data.

## What It Does

- Fetches a single spell from an Archives of Nethys detail page or the Open5e API.
- Scrapes many spells into one JSON array file.
- Supports Pathfinder 1e, Pathfinder 2e, and D&D 5e (SRD 5.2) spells.
- Uses conservative scraping defaults with configurable concurrency and delay.
- Keeps fetch, parse, scrape, and export logic separated so new systems and sources can be added without rewriting the CLI.

## Supported Pipelines

| System | Content Type | Source | Fetch | Scrape |
| --- | --- | --- | --- | --- |
| `pf2e` | `spell` | `aon-html` | yes | yes |
| `pf1e` | `spell` | `aon-html` | yes | yes |
| `dnd5e` | `spell` | `open5e` | yes | yes |

The default pipeline options are `--system pf2e --type spell --source aon-html`. `--source` defaults to `aon-html`, except when `--system dnd5e` is selected, in which case it defaults to `open5e`. The `dnd5e`/`open5e` pipeline reads the D&D 5e SRD 5.2 (2024 rules, 339 spells) from the [Open5e](https://open5e.com/) JSON API — no PDF or D&D Beyond scraping required.

## Prerequisites

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) for environment and dependency management

## Installation

```bash
uv sync
```

## Quick Start

Fetch one Pathfinder 2e spell from an AoN detail page:

```bash
uv run python cli.py "https://2e.aonprd.com/Spells.aspx?ID=1528"
```

Fetch one Pathfinder 1e spell:

```bash
uv run python cli.py fetch "https://aonprd.com/SpellDisplay.aspx?ItemName=Magic Missile" --system pf1e
```

Scrape the first 10 PF2e arcane spells into `scraped.json`:

```bash
uv run python cli.py scrape --limit 10 --tradition arcane -o scraped.json
```

Scrape PF1e spells:

```bash
uv run python cli.py scrape --system pf1e --limit 10 -o pf1e_spells.json
```

Scrape D&D 5e SRD spells from Open5e:

```bash
uv run python cli.py scrape --system dnd5e --limit 10 -o dnd5e_spells.json
```

Fetch one D&D 5e spell by its Open5e key (`--source` defaults to `open5e` for `dnd5e`):

```bash
uv run python cli.py fetch "https://api.open5e.com/v2/spells/srd-2024_fireball/" --system dnd5e
```

## CLI Usage

### Fetch

`fetch` downloads one detail page, parses it, and writes one JSON file.

```bash
uv run python cli.py fetch <AoN-spell-url> [options]
```

The `fetch` subcommand is optional. This is equivalent:

```bash
uv run python cli.py <AoN-spell-url> [options]
```

Common fetch options:

| Option | Default | Description |
| --- | --- | --- |
| `-o, --output` | generated from spell name | Output JSON file. |
| `--system` | `pf2e` | RPG system to parse. |
| `--type` | `spell` | Content type to parse. |
| `--source` | `aon-html` (`open5e` for `dnd5e`) | Source adapter to use. |

Examples:

```bash
uv run python cli.py fetch "https://2e.aonprd.com/Spells.aspx?ID=1528" -o spell.json
uv run python cli.py fetch "https://aonprd.com/SpellDisplay.aspx?ItemName=Fireball" --system pf1e
```

If `--output` is omitted, the filename is generated from the parsed spell name. Invalid filename characters become `_`, spaces become `_`, and names are lowercased.

### Scrape

`scrape` discovers many detail pages, fetches each page, parses each spell, and writes one JSON array file.

```bash
uv run python cli.py scrape [options]
```

Common scrape options:

| Option | Default | Description |
| --- | --- | --- |
| `-o, --output` | `scraped.json` | Output JSON array file. |
| `--limit` | `5000` | Maximum records to discover. |
| `--tradition` | none | PF2e spell tradition filter for AoN discovery. |
| `--workers` | `1` | Maximum concurrent detail-page requests. |
| `--delay` | `1.0` | Seconds to wait between starting detail-page requests. |
| `--location` | none | Optional source root location for discovery. |
| `--system` | `pf2e` | RPG system to parse. |
| `--type` | `spell` | Content type to parse. |
| `--source` | `aon-html` (`open5e` for `dnd5e`) | Source adapter to use. |

For larger scrapes, increase concurrency cautiously:

```bash
uv run python cli.py scrape --tradition arcane --workers 4 --delay 0.25 -o scraped.json
```

PF2e scrape discovery uses the AoN Elasticsearch endpoint. PF1e scrape discovery parses `https://aonprd.com/Spells.aspx?Class=All` for spell detail links. D&D 5e scrape discovery pages through the Open5e v2 spell list (`https://api.open5e.com/v2/spells/?document__key=srd-2024`); because that endpoint already returns the full spell objects, each one is parsed directly without a second per-spell request (so `--delay`/`--workers` have little effect for `dnd5e`). The `--tradition` filter applies only to PF2e.

## Output

JSON output uses 4-space indentation and preserves non-ASCII characters.

Example PF2e HTML output:

```json
{
    "Name": "Fireball",
    "Source": "Player Core pg. 330",
    "Traditions": "Arcane, Primal",
    "Cast": "2",
    "Range": "500 feet",
    "Area": "20-foot burst",
    "Saving Throw": "basic Reflex",
    "Description": "A roaring blast of fire appears at a spot you designate, dealing 6d6 fire damage.",
    "url": "https://2e.aonprd.com/Spells.aspx?ID=1524"
}
```

The HTML parser output preserves source-page field names where practical, such as `Name`, `Traits`, `Traditions`, and `Description`.

Example D&D 5e (Open5e) output:

```json
{
    "id": "fireball",
    "Name": "Fireball",
    "Level": 3,
    "School": "Evocation",
    "Casting Time": "action",
    "Range": "150 feet",
    "Components": "V, S, M (a ball of bat guano and sulfur)",
    "Duration": "instantaneous",
    "Ritual": false,
    "Concentration": false,
    "Classes": ["Sorcerer", "Wizard"],
    "Description": "A bright streak flashes from you to a point you choose within range ...",
    "Material": "a ball of bat guano and sulfur",
    "Higher Levels": "The damage increases by 1d6 for each spell slot level above 3.",
    "Source": "System Reference Document 5.2 © Wizards of the Coast, via Open5e (https://api.open5e.com), licensed under CC-BY-4.0",
    "key": "srd-2024_fireball"
}
```

Each D&D 5e record carries a `Source` attribution string, as required by CC-BY-4.0.

## Architecture

The project uses a small ports-and-adapters shape under `rpg_parser/`.

| Area | Path | Responsibility |
| --- | --- | --- |
| Core ports | `rpg_parser/core/ports.py` | Protocols for fetchers, parsers, scrapers, and exporters. |
| Orchestration | `rpg_parser/core/pipeline.py` | Runs fetch and scrape pipelines. |
| Adapters | `rpg_parser/adapters/` | AoN fetchers, parsers, scrapers, and JSON export. |
| Registry | `rpg_parser/registry.py` | Maps `system/type/source` combinations to pipeline implementations. |
| CLI | `cli.py` | Parses command-line arguments and invokes registered pipelines. |

To add a new RPG system, content type, or source, add the relevant adapter implementations and register them in `rpg_parser/registry.py`. Avoid wiring source-specific parser or scraper behavior directly into `cli.py`.

New fetchers should implement `requires_network(request) -> bool` as a side-effect-free
declaration alongside `fetch(request)` to satisfy the `Fetcher` protocol. For runtime
compatibility, legacy fetchers without this method are treated as network-backed;
custom fetchers used with static type checking must still implement the method.
The scrape pipeline applies `--delay`
only between network-backed fetches (or their submissions when using workers).
Embedded Open5e records skip this delay; AoN detail pages and Open5e detail URLs
retain it. Discovery pagination and HTTP retries remain the adapters' responsibility.

## Testing

Run all tests:

```bash
uv run python -m unittest discover -s tests
```

Run focused offline tests:

```bash
uv run python -m unittest tests.test_pipeline tests.test_registry tests.test_aon_scraper tests.test_scrape_pipeline tests.test_pf1e_scraper tests.test_pf2e_aon_parser tests.test_pf1e_parser
```

Run the live AoN integration test:

```bash
uv run python -m unittest tests.test_scraper.TestScraperIntegration.test_fetch_fireball
```

The live integration test requires network access and can fail if Archives of Nethys changes its API or page markup.

## Troubleshooting

- `Unsupported pipeline`: check `--system`, `--type`, and `--source` against the supported pipeline table.
- Empty or failed scrape results: try a smaller `--limit`, slower `--delay`, or verify AoN is reachable.
- Parser errors: AoN detail-page markup may have changed; compare parser behavior against files in `samples/`.

## Contributing

Contributions, bug reports, and pull requests are welcome.

When changing parser behavior, validate against the sample HTML fixtures and add or update tests for the affected system.

## License and Legal

**Disclaimer:** This is an unofficial, fan-made utility. It is **not affiliated with, endorsed by, or sponsored by Paizo Inc., Archives of Nethys, Wizards of the Coast, or Open5e.** "Pathfinder", "Archives of Nethys", "Dungeons & Dragons", "D&D", and related logos and marks are the property of their respective owners.

**Code License:** The code for this utility is released under the [MIT License](LICENSE).

**Data source and attribution:** Pathfinder data originates from [Archives of Nethys](https://aonprd.com/), which publishes Pathfinder content owned by Paizo Inc. D&D 5e data originates from the [Open5e](https://open5e.com/) API, which serves the D&D 5e System Reference Document published by Wizards of the Coast. The small sample files in `samples/` are included only as parser test fixtures. See [`ATTRIBUTION.md`](ATTRIBUTION.md) for the required notices.

**Data License:** The licensing for the game data depends on the system being parsed:

- Pathfinder 1e data is governed by the [Open Game License (OGL)](https://opengamingfoundation.org/ogl.html).
- Pathfinder 2e data is governed by the [Open RPG Creative (ORC) License](https://paizo.com/orclicense).
- D&D 5e SRD data is governed by the [Creative Commons Attribution 4.0 (CC-BY-4.0)](https://creativecommons.org/licenses/by/4.0/) license. Every parsed `dnd5e` record includes a `Source` attribution string; preserve it when redistributing. Attribute as: *"This work includes material from the System Reference Document 5.2 ('SRD 5.2') by Wizards of the Coast LLC, available under the Creative Commons Attribution 4.0 International License."*

When using, distributing, or publishing data scraped with this tool, **you** are responsible for complying with the respective license (including OGL §15 / ORC attribution obligations and the CC-BY-4.0 attribution requirement, which carry over to any redistributed output) and any other applicable policies specified by the respective rights holders.

**Responsible use:** Please scrape politely. Archives of Nethys and Open5e are community resources — use a conservative `--delay`, keep `--workers` low, and don't run large scrapes more often than you need to. The tool identifies itself with a descriptive `User-Agent`; do not modify it to impersonate a browser.
