"""Install requirements before ComfyUI imports extensions.

Adapted from ComfyUI-HakuImg; only our own setup modules are unloaded.
"""

import importlib
import logging
import sys
from pathlib import Path


def setup() -> None:
    old_path = list(sys.path)
    old_modules = set(sys.modules)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from comfyui_image_browser.runtime.requirements import setup_image_browser

        setup_image_browser()
    except Exception:
        logging.getLogger("Image-Browser").exception("Dependency setup failed. Install requirements.txt with ComfyUI's Python and restart.")
    finally:
        sys.path[:] = old_path
        for name in set(sys.modules) - old_modules:
            if name == "comfyui_image_browser" or name.startswith("comfyui_image_browser."):
                sys.modules.pop(name, None)
        importlib.invalidate_caches()


setup()
