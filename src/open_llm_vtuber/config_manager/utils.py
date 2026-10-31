# config_manager/utils.py
import yaml
from pathlib import Path
from typing import Any, TypeVar
from collections.abc import Callable
from pydantic import BaseModel, ValidationError
import os
import re
import chardet
from loguru import logger

from .main import Config
from ..utils.security import redact_secrets

T = TypeVar("T", bound=BaseModel)


def read_yaml(config_path: str) -> dict[str, Any]:
    """
    Read the specified YAML configuration file with environment variable substitution
    and guess encoding. Return the configuration data as a dictionary.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Configuration data as a dictionary.

    Raises:
        FileNotFoundError: If the configuration file is not found.
        IOError: If the configuration file cannot be read.
    """

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    content = load_text_file_with_guess_encoding(config_path)
    if not content:
        raise OSError(f"Failed to read configuration file: {config_path}")

    # Replace environment variables
    pattern = re.compile(r"\$\{(\w+)\}")

    def replacer(match):
        env_var = match.group(1)
        return os.getenv(env_var, match.group(0))

    content = pattern.sub(replacer, content)

    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as e:
        logger.critical(f"Error parsing YAML file: {e}")
        raise e


def validate_config(config_data: dict) -> Config:
    """
    Validate configuration data against the Config model.

    Args:
        config_data: Configuration data to validate.

    Returns:
        Validated Config object.

    Raises:
        ValidationError: If the configuration fails validation.
    """
    if not isinstance(config_data, dict):
        raise ValueError("Configuration root must be a mapping")

    try:
        return Config(**config_data)
    except ValidationError as e:
        # Pydantic includes the offending input in its error text; omit inputs so
        # API keys cannot end up in logs.
        logger.critical(
            f"Error validating configuration: {e.errors(include_url=False, include_input=False)}"
        )
        logger.error(
            f"Configuration data (secrets redacted): {redact_secrets(config_data)}"
        )
        raise e


def load_text_file_with_guess_encoding(file_path: str) -> str | None:
    """
    Load a text file with guessed encoding.

    Parameters:
    - file_path (str): The path to the text file.

    Returns:
    - str: The content of the text file or None if an error occurred.
    """
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "ascii", "cp936"]

    for encoding in encodings:
        try:
            with open(file_path, encoding=encoding) as file:
                return file.read()
        except UnicodeDecodeError:
            continue
    # If common encodings fail, try chardet to guess the encoding
    try:
        with open(file_path, "rb") as file:
            raw_data = file.read()
        detected = chardet.detect(raw_data)
        if detected["encoding"]:
            return raw_data.decode(detected["encoding"])
    except Exception as e:
        logger.error(f"Error detecting encoding for config file {file_path}: {e}")
    return None


def save_config(config: BaseModel, config_path: str | Path):
    """
    Saves a Pydantic model to a YAML configuration file.

    Args:
        config: The Pydantic model to save.
        config_path: Path to the YAML configuration file.
    """
    config_file = Path(config_path)
    config_data = config.model_dump(
        by_alias=True, exclude_unset=True, exclude_none=True
    )

    try:
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error writing YAML file: {e}") from e


def _config_display_name(config: Any, fallback: str) -> str:
    if not isinstance(config, dict):
        return fallback
    return config.get("character_config", {}).get("conf_name", fallback)


def scan_config_alts_directory(
    config_alts_dir: str,
    is_allowed: Callable[[dict], bool] | None = None,
) -> list[dict]:
    """
    Scan the config_alts directory and return a list of config information.
    Each config info contains the filename and its display name from the config.

    Parameters:
    - config_alts_dir (str): The path to the config_alts directory.
    - is_allowed: Optional predicate receiving a preset's raw
      ``character_config`` mapping; presets it rejects are omitted. The
      ``conf.yaml`` entry is always listed because it is the deployment-wide
      default character.

    Returns:
    - list[dict]: A list of dicts containing config info:
        - filename: The actual config file name
        - name: Display name from config, falls back to filename if not specified
    """
    config_files = []

    # Add default config first
    try:
        default_config = read_yaml("conf.yaml") or {}
    except Exception as e:
        logger.error(f"Failed to read default config: {e}")
        default_config = {}

    config_files.append(
        {
            "filename": "conf.yaml",
            "name": _config_display_name(default_config, "conf.yaml"),
        }
    )

    # Scan other configs. One malformed file must not hide every other preset.
    for root, _, files in os.walk(config_alts_dir):
        for file in files:
            if not file.endswith(".yaml"):
                continue

            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, config_alts_dir).replace(
                os.sep, "/"
            )
            try:
                config = read_yaml(full_path) or {}
                name = _config_display_name(config, relative_path)
            except Exception as e:
                logger.error(f"Failed to read character config {full_path}: {e}")
                name = relative_path
            else:
                if is_allowed is not None:
                    character_config = (
                        config.get("character_config")
                        if isinstance(config, dict)
                        else None
                    )
                    if not is_allowed(
                        character_config if isinstance(character_config, dict) else {}
                    ):
                        logger.debug(f"Hiding character config {full_path}")
                        continue

            config_files.append({"filename": relative_path, "name": name})

    config_files[1:] = sorted(config_files[1:], key=lambda item: item["filename"])
    logger.debug(f"Found config files: {config_files}")
    return config_files


def scan_bg_directory() -> list[str]:
    bg_files = []
    bg_dir = "backgrounds"
    for _root, _, files in os.walk(bg_dir):
        for file in files:
            if file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                bg_files.append(file)
    return bg_files
