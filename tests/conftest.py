"""07.11.2026: tests never write to the real run ledger (runs_ledger.jsonl); each test gets its own file."""
import pytest


@pytest.fixture(autouse=True)
def _private_run_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("GPUR_LEDGER_FILE", str(tmp_path / "test_runs_ledger.jsonl"))
    monkeypatch.delenv("GPUR_LEDGER_URL", raising=False)
