import json
import tempfile
import unittest
from pathlib import Path
from factory import (
    TopicScoutAgent, FactCheckAgent, ScriptwriterAgent,
    DistributionAgent, QualityGateAgent, AnalyticsAgent, ROOT
)


class FactoryTest(unittest.TestCase):
    def setUp(self):
        self.topic = TopicScoutAgent().discover(ROOT / "examples/netflix.json")

    def test_grounded_topic_and_storyboard(self):
        FactCheckAgent().check(self.topic)
        slides = ScriptwriterAgent().draft(self.topic)
        self.assertEqual(len(slides), 4)
        self.assertEqual(sum(x["seconds"] for x in slides), 15)
        self.assertFalse(QualityGateAgent().review(self.topic, slides)["approved_to_publish"])

    def test_export_all_platforms_without_publishing(self):
        with tempfile.TemporaryDirectory() as d:
            DistributionAgent().export(self.topic, Path(d))
            self.assertEqual(len(list(Path(d).glob("*.json"))), 4)
            for file in Path(d).glob("*.json"):
                draft = json.loads(file.read_text(encoding="utf-8"))
                self.assertIs(draft["publish"], False)
                self.assertTrue(draft["needs_approval"])

    def test_unverified_fact_rejected(self):
        from dataclasses import replace
        fake = replace(self.topic, facts=({"text": "100 миллионов",
                                          "source": "https://invalid.test"},))
        with self.assertRaises(ValueError):
            FactCheckAgent().check(fake)

    def test_metrics_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "metrics.csv"
            f.write_text(
                "platform,views,retention_pct,followers_gained\n"
                "youtube,1500,64,12\nvk,800,43,3\n", encoding="utf-8"
            )
            report = AnalyticsAgent().report(f)
            self.assertEqual(report["rows"][0]["platform"], "youtube")
            self.assertEqual(len(report["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
