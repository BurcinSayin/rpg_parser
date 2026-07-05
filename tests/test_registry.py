import unittest

from rpg_parser.adapters.exporters.json_file import JsonFileExporter
from rpg_parser.adapters.fetchers.aon import AoNHtmlFetcher
from rpg_parser.adapters.fetchers.open5e import Open5eJsonFetcher
from rpg_parser.adapters.parsers.dnd5e_open5e import Dnd5eOpen5eSpellParser
from rpg_parser.adapters.parsers.pf2e_aon import PF2eAoNSpellHtmlParser
from rpg_parser.adapters.scrapers.aon import AoNSpellScraper
from rpg_parser.adapters.scrapers.open5e import Dnd5eOpen5eSpellScraper
from rpg_parser.registry import default_source, get_pipeline, get_scrape_pipeline


class TestRegistry(unittest.TestCase):
    def test_get_pipeline_resolves_pf2e_spell_aon_html(self):
        pipeline = get_pipeline("pf2e", "spell", "aon-html")

        self.assertIsInstance(pipeline.fetcher, AoNHtmlFetcher)
        self.assertIsInstance(pipeline.parser, PF2eAoNSpellHtmlParser)
        self.assertIsInstance(pipeline.exporter, JsonFileExporter)

    def test_get_pipeline_rejects_unknown_pipeline(self):
        with self.assertRaises(ValueError):
            get_pipeline("unknown", "spell", "aon-html")

    def test_get_scrape_pipeline_resolves_pf2e_spell_aon_html(self):
        pipeline = get_scrape_pipeline("pf2e", "spell", "aon-html")

        self.assertIsInstance(pipeline.scraper, AoNSpellScraper)
        self.assertIsInstance(pipeline.fetcher, AoNHtmlFetcher)
        self.assertIsInstance(pipeline.parser, PF2eAoNSpellHtmlParser)
        self.assertIsInstance(pipeline.exporter, JsonFileExporter)

    def test_get_pipeline_resolves_dnd5e_spell_open5e(self):
        pipeline = get_pipeline("dnd5e", "spell", "open5e")

        self.assertIsInstance(pipeline.fetcher, Open5eJsonFetcher)
        self.assertIsInstance(pipeline.parser, Dnd5eOpen5eSpellParser)
        self.assertIsInstance(pipeline.exporter, JsonFileExporter)

    def test_get_scrape_pipeline_resolves_dnd5e_spell_open5e(self):
        pipeline = get_scrape_pipeline("dnd5e", "spell", "open5e")

        self.assertIsInstance(pipeline.scraper, Dnd5eOpen5eSpellScraper)
        self.assertIsInstance(pipeline.fetcher, Open5eJsonFetcher)
        self.assertIsInstance(pipeline.parser, Dnd5eOpen5eSpellParser)
        self.assertIsInstance(pipeline.exporter, JsonFileExporter)
        
    def test_default_source_dnd5e_is_open5e(self):
        self.assertEqual(default_source("dnd5e"), "open5e")

    def test_default_source_pathfinder_is_aon_html(self):
        self.assertEqual(default_source("pf2e"), "aon-html")
        self.assertEqual(default_source("pf1e"), "aon-html")

    def test_default_source_is_case_insensitive(self):
        self.assertEqual(default_source("DND5E"), "open5e")
        self.assertEqual(default_source("PF1E"), "aon-html")

    def test_default_source_unknown_system_falls_back_to_aon_html(self):
        self.assertEqual(default_source("unknown"), "aon-html")


if __name__ == "__main__":
    unittest.main()
