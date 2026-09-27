import pytest

from comfyui_image_browser.runtime.config import REQUIREMENTS_PATH, combined_view, include_temp
from comfyui_image_browser.runtime.package_analyzer import validate_requirements


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, False), ("", False), ("0", False), ("off", False), ("1", True), ("Yes", True), ("maybe", False)]
)
def test_include_temp_environment(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP", raising=False)
    else:
        monkeypatch.setenv("COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP", raw)
    assert include_temp() is expected


def test_requirements_use_extension_root():
    assert REQUIREMENTS_PATH.is_file()
    assert REQUIREMENTS_PATH.parent.name == "comfyui-image-browser"
    assert validate_requirements(REQUIREMENTS_PATH)


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, True), ("", True), ("1", True), ("On", True), ("0", False), ("false", False), ("maybe", True)]
)
def test_combined_view_environment(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("COMFYUI_IMAGE_BROWSER_COMBINED_VIEW", raising=False)
    else:
        monkeypatch.setenv("COMFYUI_IMAGE_BROWSER_COMBINED_VIEW", raw)
    assert combined_view() is expected
