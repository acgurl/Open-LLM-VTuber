import re
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "open_llm_vtuber"

# `run_server.py` imports the package as `src.open_llm_vtuber`, so an absolute
# `open_llm_vtuber.*` import inside the package only works when a second copy
# is installed (as in the Docker image). Package modules must import relatively.
_ABSOLUTE_SELF_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:src\.)?open_llm_vtuber\b", re.MULTILINE
)


class PackageImportTests(unittest.TestCase):
    def test_package_modules_import_themselves_relatively(self):
        offenders = [
            path.relative_to(PACKAGE_ROOT).as_posix()
            for path in PACKAGE_ROOT.rglob("*.py")
            if _ABSOLUTE_SELF_IMPORT.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
