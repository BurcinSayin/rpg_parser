import unittest

from rpg_parser.core.pipeline import run_pipeline
from rpg_parser.core.ports import ExportTarget, FetchRequest, PipelineSpec, RawDocument


class FakeFetcher:
    def requires_network(self, request: FetchRequest) -> bool:
        return True

    def __init__(self):
        self.calls = []

    def fetch(self, request: FetchRequest) -> RawDocument:
        self.calls.append(request)
        return RawDocument(content="raw", source=request.location)


class FakeParser:
    def __init__(self):
        self.calls = []

    def parse(self, document: RawDocument) -> dict:
        self.calls.append(document)
        return {"Name": "Fireball"}


class FakeExporter:
    def __init__(self):
        self.calls = []

    def export(self, data: dict, target: ExportTarget) -> None:
        self.calls.append((data, target))


class TestPipeline(unittest.TestCase):
    def test_run_pipeline_fetches_parses_and_exports(self):
        fetcher = FakeFetcher()
        parser = FakeParser()
        exporter = FakeExporter()
        spec = PipelineSpec(fetcher=fetcher, parser=parser, exporter=exporter)

        data = run_pipeline(
            spec,
            FetchRequest(location="https://example.test/spell"),
            ExportTarget(location="spell.json"),
        )

        self.assertEqual(data, {"Name": "Fireball"})
        self.assertEqual(fetcher.calls[0].location, "https://example.test/spell")
        self.assertEqual(parser.calls[0].content, "raw")
        self.assertEqual(exporter.calls[0][0], {"Name": "Fireball"})
        self.assertEqual(exporter.calls[0][1].location, "spell.json")


if __name__ == "__main__":
    unittest.main()
