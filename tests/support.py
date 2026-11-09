from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.sse").read_text(encoding="utf-8")
