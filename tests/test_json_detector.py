import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.mcpp.json_detector import StreamJSONDetector
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class StreamJSONDetectorTests(unittest.TestCase):
    def test_brace_inside_string_does_not_end_json(self):
        detector = StreamJSONDetector()

        found = detector.process_chunk('{"text": "a}b"}')

        self.assertEqual(found, [{"text": "a}b"}])

    def test_escaped_quote_inside_string(self):
        detector = StreamJSONDetector()

        found = detector.process_chunk('{"text": "a\\"}b"}')

        self.assertEqual(found, [{"text": 'a"}b'}])

    def test_incomplete_string_stays_pending(self):
        detector = StreamJSONDetector()

        self.assertEqual(detector.process_chunk('{"text": "a}b'), [])
        self.assertEqual(detector.process_chunk('"}'), [{"text": "a}b"}])

    def test_multiple_objects_in_one_chunk(self):
        detector = StreamJSONDetector()

        found = detector.process_chunk('{"a": "}{"} and {"b": 2}')

        self.assertEqual(found, [{"a": "}{"}, {"b": 2}])


if __name__ == "__main__":
    unittest.main()
