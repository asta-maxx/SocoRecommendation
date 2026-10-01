"""ENG-02 item 2: the twelve modules, and the two gatekeepers. SD-05, SD-06.

Only platform reads the platform database. Only store writes, and only to the
engine database. Both are checked by reading the source, so a new file that
breaks either rule fails here rather than in review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "reco"

#: SD-05, in the order the agreement lists them.
MODULES = (
    "api", "config", "slots", "store", "platform", "eligibility",
    "ranking", "fallback", "sync", "jobs", "fraud", "monitoring",
)

#: Calls that change a database. Only reco/store may make them.
WRITE_CALLS = {
    "insert_one", "insert_many", "update_one", "update_many", "replace_one",
    "delete_one", "delete_many", "bulk_write", "find_one_and_update",
    "find_one_and_replace", "find_one_and_delete", "create_index",
    "create_indexes", "drop", "drop_index", "drop_indexes", "create_collection",
    "drop_collection", "rename",
}

#: The entry points (API, health, jobs) may hold the platform connection, but only to open,
#: close and ping it. None of them reads platform data.
PLATFORM_CONNECTION_WIRING = {Path("main.py"), Path("api/health.py"), Path("jobs/__main__.py")}


def _sources() -> list[tuple[Path, ast.Module]]:
    return [
        (path.relative_to(PACKAGE), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(PACKAGE.rglob("*.py"))
    ]


def _module_of(relative: Path) -> str:
    return relative.parts[0] if len(relative.parts) > 1 else ""


def test_the_package_holds_exactly_the_twelve_modules() -> None:
    packages = {
        path.name
        for path in PACKAGE.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert packages == set(MODULES)
    for module in MODULES:
        assert (PACKAGE / module / "__init__.py").exists(), f"{module} is not a package"


def test_only_platform_uses_the_platform_database() -> None:
    offenders = []
    for relative, tree in _sources():
        if _module_of(relative) == "platform" or relative in PLATFORM_CONNECTION_WIRING:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "reco.platform.connection":
                offenders.append(f"{relative}:{node.lineno} imports reco.platform.connection")
            if isinstance(node, ast.ImportFrom) and node.module == "reco.platform":
                if any(alias.name == "connection" for alias in node.names):
                    offenders.append(f"{relative}:{node.lineno} imports reco.platform.connection")
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name == "app_db":
                    offenders.append(f"{relative}:{node.lineno} uses app_db")
    assert not offenders, "only reco/platform may read the platform database: " + "; ".join(offenders)


def test_wiring_files_only_open_close_and_ping_the_platform_connection() -> None:
    allowed = {"init_client", "close_client", "verify_database", "ping"}
    for relative in PLATFORM_CONNECTION_WIRING:
        tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "platform_conn"
        }
        assert used <= allowed, f"{relative} uses {sorted(used - allowed)} on the platform connection"


def test_only_store_writes() -> None:
    offenders = [
        f"{relative}:{node.lineno} calls .{node.func.attr}()"
        for relative, tree in _sources()
        if _module_of(relative) != "store"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in WRITE_CALLS
    ]
    assert not offenders, "only reco/store may write: " + "; ".join(offenders)


@pytest.mark.parametrize("module", MODULES)
def test_every_module_says_what_it_is_for(module: str) -> None:
    tree = ast.parse((PACKAGE / module / "__init__.py").read_text(encoding="utf-8"))
    assert ast.get_docstring(tree), f"reco/{module}/__init__.py needs a docstring"
