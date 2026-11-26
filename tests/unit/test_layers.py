"""The three layers stay separate: data -> logic <- bot, and logic never touches I/O."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "polybot"
IO_LIBRARIES = {"sqlalchemy", "httpx", "redis", "aiogram", "websockets", "asyncpg", "aiosqlite", "pydantic_settings"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_logic_layer_has_no_io_and_no_upward_imports() -> None:
    offenders = []
    for path in sorted((PKG / "logic").glob("*.py")):
        for name in _imports(path):
            top = name.split(".")[0]
            if top in IO_LIBRARIES or name.startswith(("polybot.data", "polybot.services", "polybot.bot")):
                offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_data_layer_does_not_import_services_or_bot() -> None:
    offenders = [
        f"{path.name}: {name}"
        for path in sorted((PKG / "data").glob("*.py"))
        for name in _imports(path)
        if name.startswith(("polybot.services", "polybot.bot"))
    ]
    assert offenders == []


def test_flat_layout_one_level_of_packages() -> None:
    packages = sorted(p.name for p in PKG.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert packages == ["bot", "data", "logic", "services"]
    for layer in packages:
        assert not [p for p in (PKG / layer).iterdir() if p.is_dir() and p.name != "__pycache__"]
