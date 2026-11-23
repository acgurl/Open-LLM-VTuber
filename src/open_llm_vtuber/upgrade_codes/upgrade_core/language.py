import os
import sys
import ctypes
import locale
import platform
import subprocess


def _windows_language() -> str | None:
    try:
        # Use Windows API to get the UI language
        windll = ctypes.windll.kernel32  # type: ignore
        ui_lang = windll.GetUserDefaultUILanguage()
        lang_code = locale.windows_locale.get(ui_lang)
        if lang_code and lang_code.split("_")[0].startswith("zh"):
            return "zh"
    except Exception:
        pass
    return None


def _darwin_language() -> str | None:
    try:
        # Use defaults command to get the AppleLocale
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip().split("_")[0].startswith("zh"):
            return "zh"
    except Exception:
        pass
    return None


def _linux_language() -> str | None:
    # Check the LANG environment variable
    lang = os.environ.get("LANG")
    if lang and lang.split("_")[0].startswith("zh"):
        return "zh"
    return None


def get_system_language():
    """Get system language using a combination of methods."""
    detectors = {
        "Windows": _windows_language,
        "Darwin": _darwin_language,
        "Linux": _linux_language,
    }
    detector = detectors.get(platform.system())
    detected = detector() if detector is not None else None
    if detected is not None:
        return detected

    # Fallback to using locale.getpreferredencoding()
    encoding = locale.getpreferredencoding()
    if encoding.lower() in ("cp936", "gbk", "big5"):
        return "zh"

    return "en"


def select_language():
    """Select language based on command-line argument or system language"""
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["zh", "en"]:
        return sys.argv[1].lower()
    return get_system_language()
