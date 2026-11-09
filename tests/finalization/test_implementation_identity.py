from agent_reliability_lab.evaluation.versions import implementation_identity


def test_scoring_identity_covers_shared_provenance_code_and_lock(tmp_path):
    package = tmp_path / "package"
    (package / "agent").mkdir(parents=True)
    (package / "evaluation").mkdir()
    (package / "evaluation/scoring.py").write_text("score = 1\n")
    helper = package / "agent/provenance.py"
    helper.write_text("verify = 1\n")
    lock = tmp_path / "uv.lock"
    lock.write_text("version = 1\n")
    before = implementation_identity(package, lock)
    assert before == implementation_identity(package, lock)
    helper.write_text("verify = 2\n")
    changed = implementation_identity(package, lock)
    assert before["scoring_implementation_hash"] != changed["scoring_implementation_hash"]
    assert before["dependency_lock_hash"] == changed["dependency_lock_hash"]
    lock.write_text("version = 2\n")
    locked = implementation_identity(package, lock)
    assert locked["scoring_implementation_hash"] != changed["scoring_implementation_hash"]
    assert locked["dependency_lock_hash"] != changed["dependency_lock_hash"]
