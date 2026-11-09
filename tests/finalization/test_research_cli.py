import sys
from pathlib import Path

from agent_reliability_lab.research.cli import main


def test_split_validation_requires_no_database_configuration(monkeypatch, capsys):
    monkeypatch.delenv("OPSDESK_DATABASE_URL", raising=False)
    monkeypatch.delenv("OPSDESK_ALLOW_SANDBOX", raising=False)
    path = Path(__file__).parents[2] / "benchmarks/research/split-held_out.json"
    monkeypatch.setattr(sys, "argv", ["opsdesk-research", "validate", str(path)])
    main()
    assert '"generalization_validated": false' in capsys.readouterr().out
