"""Check and install dependencies using the interpreter running ComfyUI."""

import importlib
import os
import sys

from .cmd import run_cmd
from .config import LOGGER_COLOR, LOGGER_LEVEL, LOGGER_NAME, REQUIREMENTS_PATH
from .logger import get_logger
from .package_analyzer import validate_requirements

logger = get_logger(LOGGER_NAME, LOGGER_LEVEL, LOGGER_COLOR)


def setup_image_browser() -> None:
    """Install only missing or incompatible requirements, unless explicitly disabled."""
    if os.getenv("COMFYUI_IMAGE_BROWSER_AUTO_INSTALL", "1").lower() in {"0", "false", "no"}:
        logger.info("Automatic dependency installation is disabled")
        return
    logger.info("Checking Hanaikada requirements")
    if not validate_requirements(REQUIREMENTS_PATH):
        run_cmd([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)], shell=False)
        importlib.invalidate_caches()
        if not validate_requirements(REQUIREMENTS_PATH):
            raise RuntimeError("Hanaikada requirements are still incomplete; check the pip output above")
    logger.info("Checking Hanaikada requirements done")
