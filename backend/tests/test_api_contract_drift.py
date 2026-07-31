"""
The frontend's TypeScript interfaces must not read fields the backend stopped
sending.

`tests/test_dividend_summary_contract.py` pins one endpoint's key set against its
`response_model`, for a reason that generalises: a `response_model` is a *filter*,
so an undeclared key is dropped silently, and a key the client reads but the
server never sends arrives as `undefined` with no error anywhere. TypeScript
cannot catch either — it describes what we *believe* the wire carries, and
believing wrongly is exactly the failure.

This walks every Pydantic model whose name matches a TS interface exactly, so it
needs no hand-maintained pairing list and covers new models the day they are
added.

**The two directions are not symmetric, deliberately.** A field the frontend
declares and the backend does not send is a silent `undefined` and fails here. A
field the backend sends and the frontend does not read is fine and common —
`SecurityAttribution.disposal_proceeds_eur` is on the wire and unused — so it is
reported for information rather than failed on.

Skips entirely when `frontend/` is absent: the Docker image copies only `app/` and
`alembic/`, so the suite has to run there too.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
API_TS = REPO / "frontend" / "src" / "lib" / "api.ts"
SCHEMAS = BACKEND / "app" / "schemas"

pytestmark = pytest.mark.skipif(
    not API_TS.exists(), reason="frontend/ is not present (Docker image ships app/ only)"
)


def _pydantic_models() -> dict[str, set[str]]:
    """Field names of every `class X(BaseModel)` under app/schemas."""
    out: dict[str, set[str]] = {}
    for path in sorted(SCHEMAS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"^class (\w+)\(BaseModel\):(.*?)(?=^class |\Z)", src, re.S | re.M
        ):
            name, body = match.group(1), match.group(2)
            fields = set(re.findall(r"^    (\w+)\s*:", body, re.M)) - {"model_config"}
            if fields:
                out[name] = fields
    return out


def _ts_interfaces() -> dict[str, set[str]]:
    """Field names of every `export interface X { ... }` in api.ts."""
    src = API_TS.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for match in re.finditer(r"export interface (\w+)\s*\{(.*?)\n\}", src, re.S):
        name, body = match.group(1), match.group(2)
        fields = set(re.findall(r"^\s{2}(\w+)\??\s*:", body, re.M))
        if fields:
            out[name] = fields
    return out


MODELS = _pydantic_models() if API_TS.exists() else {}
INTERFACES = _ts_interfaces() if API_TS.exists() else {}
PAIRED = sorted(set(MODELS) & set(INTERFACES))


def test_the_pairing_finds_something():
    """
    A regex that quietly stops matching would turn every assertion below into a
    vacuous pass, which is worse than no test.
    """
    assert len(MODELS) > 20, f"only parsed {len(MODELS)} Pydantic models"
    assert len(INTERFACES) > 20, f"only parsed {len(INTERFACES)} TS interfaces"
    assert len(PAIRED) > 15, f"only {len(PAIRED)} names paired: {PAIRED}"


@pytest.mark.parametrize("name", PAIRED)
def test_the_frontend_reads_no_field_the_backend_stopped_sending(name):
    missing = INTERFACES[name] - MODELS[name]
    assert not missing, (
        f"{name}: the TS interface declares {sorted(missing)}, which the Pydantic "
        f"model does not send. A `response_model` filters undeclared keys, so these "
        f"arrive as `undefined` with nothing raising — add them to the model, or "
        f"drop them from the interface."
    )


def test_backend_only_fields_are_reported_but_allowed(capsys):
    """
    Not a failure: the wire may legitimately carry more than any screen renders.
    Printed so an intentionally-unused field stays visible rather than becoming
    invisible dead weight nobody can justify.
    """
    unread = {
        name: sorted(MODELS[name] - INTERFACES[name])
        for name in PAIRED
        if MODELS[name] - INTERFACES[name]
    }
    if unread:
        print("\nOn the wire but unread by the frontend:")
        for name, fields in sorted(unread.items()):
            print(f"  {name}: {', '.join(fields)}")
    # Only that the check ran; the assertion is the printout.
    assert isinstance(unread, dict)
