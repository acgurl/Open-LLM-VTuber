# config_manager/asset_access.py
"""Per-user access to character assets served as static files.

``allowed_users`` on a preset (see ``access.py``) hides the character from
other accounts, but its Live2D model folder and avatar are plain static files.
This module derives which of those files are private:

- the model folder is the first path segment after ``/live2d-models/`` in the
  ``model_dict.json`` URL of the preset's ``live2d_model_name``;
- the avatar is ``avatars/<character_config.avatar>``.

An asset is private only when every character that uses it is restricted; one
public character (including the ``conf.yaml`` default, which is always public)
keeps it public. A private asset is readable by the union of the allowlists of
the characters that use it.
"""

import json
import os
import threading
import time
from collections.abc import Iterable
from typing import Any

from loguru import logger

from .access import (
    is_user_allowed,
    parse_allowed_users,
    warn_unmatched_allowlist_entries,
)
from .utils import read_yaml

LIVE2D_MOUNT = "live2d-models"
AVATAR_MOUNT = "avatars"
_LIVE2D_URL_PREFIX = "/live2d-models/"

# Marks an asset used by at least one public character.
_PUBLIC = object()


def _normalize_key(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _asset_key(mount: str, path: str) -> tuple[str, str] | None:
    """Map a path relative to a static mount to the asset it belongs to."""
    rel = _normalize_key(path)
    if not rel:
        return None
    if mount == LIVE2D_MOUNT:
        return (mount, rel.split("/", 1)[0].casefold())
    if mount == AVATAR_MOUNT:
        return (mount, rel.casefold())
    return None


def _model_folder(model_url: Any) -> str | None:
    if not isinstance(model_url, str) or not model_url.startswith(_LIVE2D_URL_PREFIX):
        return None
    folder = model_url[len(_LIVE2D_URL_PREFIX) :].split("/", 1)[0]
    return folder or None


class CharacterAssetAccess:
    """Resolve whether a static character asset is visible to a user.

    Rules are rebuilt from ``conf.yaml``, the preset directory and
    ``model_dict.json`` whenever one of them changes (checked at most every
    ``refresh_interval`` seconds), so editing a preset takes effect without a
    restart, like the character list does.
    """

    def __init__(
        self,
        config_alts_dir: str,
        model_dict_path: str = "model_dict.json",
        default_config_path: str = "conf.yaml",
        refresh_interval: float = 5.0,
    ) -> None:
        self.config_alts_dir = config_alts_dir
        self.model_dict_path = model_dict_path
        self.default_config_path = default_config_path
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._signature: tuple | None = None
        self._rules: dict[tuple[str, str], Any] = {}

    def is_restricted(self, mount: str, path: str) -> bool:
        key = _asset_key(mount, path)
        if key is None:
            return False
        rule = self._current_rules().get(key)
        return rule is not None and rule is not _PUBLIC

    def is_allowed(
        self,
        mount: str,
        path: str,
        user_id: str | None,
        emails: str | Iterable[str] | None,
    ) -> bool:
        """``emails`` are the user's verified login emails."""
        key = _asset_key(mount, path)
        if key is None:
            return True
        rule = self._current_rules().get(key)
        if rule is None or rule is _PUBLIC:
            return True
        if not isinstance(emails, str) and emails is not None:
            emails = tuple(emails)
        return any(is_user_allowed(allowed, user_id, emails) for allowed in rule)

    def warn_unmatched_allowlists(self) -> None:
        """Warn about preset allowlist entries that cannot match anyone now."""
        for path in self._preset_files():
            try:
                config = read_yaml(path) or {}
            except Exception:
                continue
            character = (
                config.get("character_config") if isinstance(config, dict) else None
            )
            if isinstance(character, dict):
                warn_unmatched_allowlist_entries(character.get("allowed_users"), path)

    # ---- rule loading

    def _preset_files(self) -> list[str]:
        files = []
        for root, _, names in os.walk(self.config_alts_dir):
            files.extend(
                os.path.join(root, name) for name in names if name.endswith(".yaml")
            )
        return sorted(files)

    def _compute_signature(self, presets: Iterable[str]) -> tuple:
        signature = []
        for path in (self.default_config_path, self.model_dict_path, *presets):
            try:
                stat = os.stat(path)
            except OSError:
                signature.append((path, None))
            else:
                signature.append((path, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _current_rules(self) -> dict[tuple[str, str], Any]:
        with self._lock:
            now = time.monotonic()
            if (
                self._checked_at is not None
                and now - self._checked_at < self.refresh_interval
            ):
                return self._rules
            self._checked_at = now
            presets = self._preset_files()
            signature = self._compute_signature(presets)
            if signature != self._signature:
                self._rules = self._build_rules(presets)
                self._signature = signature
            return self._rules

    def _load_model_folders(self) -> dict[str, str]:
        try:
            with open(self.model_dict_path, encoding="utf-8") as file:
                entries = json.load(file)
        except (OSError, ValueError) as e:
            logger.warning(f"Asset access: cannot read {self.model_dict_path}: {e}")
            return {}
        folders = {}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            folder = _model_folder(entry.get("url"))
            if folder:
                folders[entry["name"]] = folder
        return folders

    def _build_rules(self, presets: list[str]) -> dict[tuple[str, str], Any]:
        model_folders = self._load_model_folders()
        rules: dict[tuple[str, str], Any] = {}

        def add(character: dict, public: bool) -> None:
            allowed = character.get("allowed_users")
            if not public:
                scope = parse_allowed_users(allowed)
                public = isinstance(scope, tuple) and not scope
            keys = []
            folder = model_folders.get(character.get("live2d_model_name"))
            if folder:
                keys.append((LIVE2D_MOUNT, folder.casefold()))
            avatar = character.get("avatar")
            if isinstance(avatar, str) and _normalize_key(avatar):
                keys.append((AVATAR_MOUNT, _normalize_key(avatar).casefold()))
            for key in keys:
                current = rules.get(key)
                if public or current is _PUBLIC:
                    rules[key] = _PUBLIC
                else:
                    rules.setdefault(key, []).append(allowed)

        for path, public in [(self.default_config_path, True)] + [
            (preset, False) for preset in presets
        ]:
            try:
                config = read_yaml(path) or {}
            except Exception as e:
                logger.warning(f"Asset access: cannot read {path}: {e}")
                continue
            character = (
                config.get("character_config") if isinstance(config, dict) else None
            )
            if isinstance(character, dict):
                add(character, public)

        restricted = sorted(
            f"{mount}/{name}"
            for (mount, name), rule in rules.items()
            if rule is not _PUBLIC
        )
        if restricted:
            logger.info(f"Restricted character assets: {', '.join(restricted)}")
        return rules
