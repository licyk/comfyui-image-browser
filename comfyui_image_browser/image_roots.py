"""Translate ComfyUI's image directories into stable Hanaikada roots."""

import os
from dataclasses import dataclass
from pathlib import Path

# ComfyUI's result types; the frontend reports saved files by these names.
OUTPUT, INPUT, TEMP = "output", "input", "temp"
ROOT_IDS = {OUTPUT: "comfyui-output", INPUT: "comfyui-input", TEMP: "comfyui-temp"}


@dataclass(frozen=True)
class RootSpec:
    kind: str
    path: str
    index: bool = True

    @property
    def id(self) -> str:
        return ROOT_IDS[self.kind]


def collect_image_roots(output: str | Path, input: str | Path, temp: str | Path | None = None) -> list[RootSpec]:
    """Output first, so Browse opens there. Each directory is its own "custom" root.

    Hanaikada's "comfyui" layout expects an installation folder and would show only a nested
    ``output/`` folder, but ``--output-directory`` points straight at the images. The output
    folder is created because ComfyUI only creates it on the first save; the others are skipped
    when missing. A directory registered twice (for example input == output) appears once.
    """
    roots: list[RootSpec] = []
    seen: set[str] = set()
    for kind, directory in ((OUTPUT, output), (INPUT, input), (TEMP, temp)):
        if directory is None:
            continue
        path = str(Path(directory).expanduser().resolve())
        if kind == OUTPUT:
            os.makedirs(path, exist_ok=True)
        identity = os.path.normcase(path)
        if identity in seen or not os.path.isdir(path):
            continue
        seen.add(identity)
        # Temp files are replaced on every run and deleted on every start; browse them only.
        roots.append(RootSpec(kind, path, index=kind != TEMP))
    return roots
