"""Keeps pik.yaml's version reset in step with each release."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_pik_resets_the_current_release_version_to_0_1_0() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    manifest = (ROOT / "pik.yaml").read_text()
    assert f'version = \\"{version}\\"' in manifest, (
        f"pik.yaml must reset version {version} to 0.1.0 in pyproject.toml and uv.lock"
    )
    assert f'\\"version\\": \\"{version}\\"' in manifest, (
        f"pik.yaml must reset version {version} to 0.1.0 in openapi.json"
    )
