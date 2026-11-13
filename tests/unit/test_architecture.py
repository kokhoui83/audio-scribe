"""The dependency rule: code may only depend on layers further in.

entrypoints -> bootstrap -> adapters -> application -> domain
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2] / "scribe"
FORBIDDEN = {
    "domain": (
        "scribe.application",
        "scribe.adapters",
        "scribe.entrypoints",
        "scribe.bootstrap",
        "scribe.settings",
    ),
    "application": ("scribe.adapters", "scribe.entrypoints", "scribe.bootstrap", "scribe.settings"),
    "adapters": ("scribe.entrypoints", "scribe.bootstrap", "scribe.settings"),
}
THIRD_PARTY_FREE = ("domain", "application")
FRAMEWORKS = (
    "fastapi",
    "psycopg",
    "psycopg_pool",
    "numpy",
    "torch",
    "faster_whisper",
    "pyannote",
    "pydantic",
)


def imports(path: Path) -> set[str]:
    package = ".".join(path.relative_to(ROOT.parent).parent.parts)
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package.rsplit(".", node.level - 1)[0] if node.level else ""
            found.add(".".join(part for part in (base, node.module or "") if part))
    return found


def modules(layer: str) -> list[Path]:
    return sorted((ROOT / layer).rglob("*.py"))


@pytest.mark.parametrize("layer", FORBIDDEN)
def test_layers_only_depend_inwards(layer):
    for path in modules(layer):
        for name in imports(path):
            assert not name.startswith(FORBIDDEN[layer]), f"{path.relative_to(ROOT)} imports {name}"


@pytest.mark.parametrize("layer", THIRD_PARTY_FREE)
def test_business_code_is_free_of_frameworks(layer):
    for path in modules(layer):
        for name in imports(path):
            assert name.split(".")[0] not in FRAMEWORKS, f"{path.relative_to(ROOT)} imports {name}"


def test_only_the_composition_root_and_entrypoints_wire_adapters():
    for path in sorted(ROOT.rglob("*.py")):
        layer = path.relative_to(ROOT).parts[0]
        if layer in ("bootstrap.py", "entrypoints", "adapters"):
            continue
        assert not any(n.startswith("scribe.adapters") for n in imports(path)), path
