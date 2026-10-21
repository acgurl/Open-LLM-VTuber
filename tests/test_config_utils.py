import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from open_llm_vtuber.config_manager.utils import scan_config_alts_directory  # noqa: E402


class ScanConfigAltsDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.alts = self.root / "characters"
        self.alts.mkdir()
        (self.alts / "nested").mkdir()

        (self.root / "conf.yaml").write_text(
            "character_config:\n  conf_name: Default Character\n",
            encoding="utf-8",
        )
        (self.alts / "alpha.yaml").write_text(
            "character_config:\n  conf_name: Alpha\n",
            encoding="utf-8",
        )
        (self.alts / "beta.yaml").write_text(
            "character_config:\n  conf_uid: beta\n",
            encoding="utf-8",
        )
        (self.alts / "broken.yaml").write_text(
            "character_config: [unclosed\n",
            encoding="utf-8",
        )
        (self.alts / "notes.txt").write_text("ignored", encoding="utf-8")
        (self.alts / "nested" / "gamma.yaml").write_text(
            "character_config:\n  conf_name: Gamma\n",
            encoding="utf-8",
        )

        self.original_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_scans_default_and_presets_with_fallbacks(self) -> None:
        configs = scan_config_alts_directory(str(self.alts))

        self.assertEqual(
            configs[0],
            {"filename": "conf.yaml", "name": "Default Character"},
        )
        names = {item["filename"]: item["name"] for item in configs}
        self.assertEqual(names["alpha.yaml"], "Alpha")
        self.assertEqual(names["nested/gamma.yaml"], "Gamma")
        self.assertEqual(names["beta.yaml"], "beta.yaml")
        self.assertEqual(names["broken.yaml"], "broken.yaml")
        self.assertNotIn("notes.txt", names)
        self.assertEqual(len(configs), 5)

        preset_filenames = [item["filename"] for item in configs[1:]]
        self.assertEqual(preset_filenames, sorted(preset_filenames))


if __name__ == "__main__":
    unittest.main()
