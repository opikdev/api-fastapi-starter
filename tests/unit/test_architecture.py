"""Keeps imports pointing one way. Fails the build when a module reaches across a boundary."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "app"

FORBIDDEN = {
    "app/config.py": ("app.",),
    "app/ids.py": ("app.",),
    "app/security.py": ("app.", "fastapi"),
    "app/problems.py": ("app.",),
    "app/db.py": ("app.features", "app.main"),
    "app/jobs.py": ("app.features", "app.main", "fastapi"),
    "app/features/auth": ("app.features.notes", "app.main"),
    "app/features/notes": ("app.features.auth.routes", "app.main"),
}


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_dependencies_point_one_way() -> None:
    checked = 0
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC.parent).as_posix()
        for scope, banned in FORBIDDEN.items():
            if relative == scope or relative.startswith(scope + "/"):
                checked += 1
                for name in imports(path):
                    assert not name.startswith(banned), f"{relative} must not import {name}"
    assert checked >= len(FORBIDDEN)
