"""Configuration shared by dependency setup and the extension."""

import logging
import os
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = ROOT_PATH / "requirements.txt"
LOGGER_NAME = os.getenv("COMFYUI_IMAGE_BROWSER_LOGGER_NAME", "Image-Browser")
LOGGER_LEVEL = int(os.getenv("COMFYUI_IMAGE_BROWSER_LOGGER_LEVEL", str(logging.INFO)))
LOGGER_COLOR = os.getenv("COMFYUI_IMAGE_BROWSER_LOGGER_COLOR", "1").lower() not in {"0", "false", "none"}


def public_base_url() -> str | None:
    """The browser's URL of the proxied UI, for proxies that remove browser origin metadata."""
    return os.getenv("COMFYUI_IMAGE_BROWSER_PUBLIC_BASE_URL") or None


def include_temp() -> bool:
    """ComfyUI empties its temp folder on every start, so previews are opt-in."""
    raw = os.getenv("COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP", "").strip().lower()
    if not raw or raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    logging.getLogger(LOGGER_NAME).warning("Ignoring COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP=%r; use 1 or 0", raw)
    return False


def combined_view() -> bool:
    """Pin Hanaikada's "All folders" browse entry: on unless the administrator turns it off."""
    raw = os.getenv("COMFYUI_IMAGE_BROWSER_COMBINED_VIEW", "").strip().lower()
    if not raw or raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    logging.getLogger(LOGGER_NAME).warning("Ignoring COMFYUI_IMAGE_BROWSER_COMBINED_VIEW=%r; use 1 or 0", raw)
    return True
