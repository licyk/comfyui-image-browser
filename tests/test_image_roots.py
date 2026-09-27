from comfyui_image_browser.image_roots import collect_image_roots


def test_output_leads_and_temp_is_browse_only(tmp_path):
    for name in ("output", "input", "temp"):
        (tmp_path / name).mkdir()
    roots = collect_image_roots(tmp_path / "output", tmp_path / "input", tmp_path / "temp")
    assert [(root.kind, root.id, root.index) for root in roots] == [
        ("output", "comfyui-output", True),
        ("input", "comfyui-input", True),
        ("temp", "comfyui-temp", False),
    ]
    assert roots[0].path == str((tmp_path / "output").resolve())


def test_output_is_created_and_missing_folders_skipped(tmp_path):
    roots = collect_image_roots(tmp_path / "custom" / "out", tmp_path / "missing-input", tmp_path / "missing-temp")
    assert [root.kind for root in roots] == ["output"]
    assert (tmp_path / "custom" / "out").is_dir()
    assert not (tmp_path / "missing-input").exists()


def test_shared_and_symlinked_directories_appear_once(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "images", target_is_directory=True)
    roots = collect_image_roots(tmp_path / "images", tmp_path / "alias")
    assert [root.kind for root in roots] == ["output"]
