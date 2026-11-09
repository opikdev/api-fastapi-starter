"""Keeps imports pointing one way. Fails the build when a module reaches across a boundary."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "app"
FEATURES = sorted(path.name for path in (SRC / "features").iterdir() if path.is_dir())
SHARED_FEATURE_MODULE = "app.features.auth.dependencies"

FORBIDDEN = {
    "app/config.py": ("app.",),
    "app/ids.py": ("app.",),
    "app/security.py": ("app.", "fastapi"),
    "app/problems.py": ("app.",),
    "app/db.py": ("app.features", "app.main", "fastapi", "starlette"),
    "app/dependencies.py": ("app.features", "app.main"),
    "app/jobs.py": ("app.features", "app.main", "fastapi", "starlette"),
    "app/features": ("app.main",),
}


def module_name(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


MODULES = {module_name(path): path for path in SRC.rglob("*.py")}


def imports(path: Path) -> set[str]:
    """Every imported name, with `from a import b` recorded as `a.b`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def loaded_modules(start: str) -> set[str]:
    """The app modules Python loads when it imports `start`, parent packages included."""
    seen: set[str] = set()
    pending = [start]
    while pending:
        name = pending.pop()
        parts = name.split(".")
        for end in range(1, len(parts) + 1):
            module = ".".join(parts[:end])
            if module in MODULES and module not in seen:
                seen.add(module)
                pending.extend(imports(MODULES[module]))
    return seen


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


def test_features_import_no_other_feature_except_auth_dependencies() -> None:
    assert len(FEATURES) >= 2
    for feature in FEATURES:
        for path in (SRC / "features" / feature).rglob("*.py"):
            for name in imports(path):
                parts = name.split(".")
                if parts[:2] != ["app", "features"] or len(parts) < 3 or parts[2] == feature:
                    continue
                assert name.startswith(SHARED_FEATURE_MODULE + "."), (
                    f"{path.relative_to(SRC.parent)} must not import {name}. "
                    f"Features may only share {SHARED_FEATURE_MODULE}"
                )


def test_jobs_never_load_fastapi_even_indirectly() -> None:
    loaded = loaded_modules("app.jobs")
    assert "app.db" in loaded
    for module in loaded:
        for name in imports(MODULES[module]):
            assert not name.startswith(("fastapi", "starlette")), (
                f"app.jobs loads {module}, which imports {name}"
            )
