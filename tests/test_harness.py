"""Harness integrity tests.

These exist for the same reason `test_contract.py` does: an artefact that is only checked
when someone remembers is not checked. The feature lock, the session log index, and the
one-feature-at-a-time policy are all enforceable, so they are enforced.

The lock test is the important one. It fails when a locked field of a feature changed
without a `lock_version` bump and a changelog entry — which is exactly what "scope drifted
and nobody decided to drift it" looks like from the outside.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness as H  # noqa: E402


@pytest.fixture(scope="module")
def ledger() -> dict:
    return H.load()


# ---------------------------------------------------------------- lock integrity
def test_lock_file_matches_the_ledger(ledger):
    """The whole point of the lock. See the failure message for what to do about it."""
    lock = H.read_lock()
    assert lock is not None, "harness/features.lock missing — run: harness.py relock"
    assert lock["sha256"] == H.lock_hash(ledger), (
        "FEATURE LOCK DRIFT — a locked field changed without a lock_version bump.\n"
        "Locked fields: id, area, title, why, depends_on, acceptance, verify, milestone.\n"
        "If intentional: bump lock_version, add a changelog entry saying what changed and "
        "why, then run `python scripts/harness.py relock`."
    )
    assert lock["lock_version"] == ledger["lock_version"]


def test_lock_version_has_a_changelog_entry(ledger):
    versions = {c["lock_version"] for c in ledger["changelog"]}
    assert ledger["lock_version"] in versions
    for entry in ledger["changelog"]:
        assert len(entry["change"]) >= 20, "a changelog entry that says nothing is not one"


def test_lock_hash_ignores_mutable_fields(ledger):
    """Progress must not churn the hash, or the lock becomes noise and gets ignored."""
    before = H.lock_hash(ledger)
    mutated = json.loads(json.dumps(ledger))
    target = next(f for f in mutated["features"] if f["status"] == "locked")
    target["status"] = "in_progress"
    target["sessions"] = ["9999"]
    target["notes"] = "scratch"
    assert H.lock_hash(mutated) == before


def test_lock_hash_catches_a_changed_acceptance_criterion(ledger):
    mutated = json.loads(json.dumps(ledger))
    mutated["features"][-1]["acceptance"][0] = "something quietly easier"
    assert H.lock_hash(mutated) != H.lock_hash(ledger)


# ---------------------------------------------------------------- ledger validity
def test_ledger_validates(ledger):
    assert H.validate(ledger) == []


def test_every_feature_is_checkable_by_a_command(ledger):
    """'Human review' is not a verification gate — HARNESS_CHECKLIST.md, verification loop."""
    for f in ledger["features"]:
        assert f["verify"].strip(), f["id"]
        assert len(f["acceptance"]) >= 2, f["id"]


def test_at_most_one_feature_in_progress(ledger):
    active = [f["id"] for f in ledger["features"] if f["status"] == "in_progress"]
    assert len(active) <= 1, f"policy one_at_a_time violated: {active}"


def test_dependency_graph_is_acyclic_and_resolvable(ledger):
    by_id = H.features_by_id(ledger)
    assert H._cycle(by_id) == []
    for f in ledger["features"]:
        for dep in f["depends_on"]:
            assert dep in by_id, f"{f['id']} depends on unknown {dep}"


def test_done_features_do_not_stand_on_unfinished_dependencies(ledger):
    by_id = H.features_by_id(ledger)
    for f in ledger["features"]:
        if f["status"] != "done":
            continue
        for dep in f["depends_on"]:
            assert by_id[dep]["status"] in ("done", "dropped"), \
                f"{f['id']} is done but {dep} is {by_id[dep]['status']}"


def test_ledger_conforms_to_its_own_schema_fields(ledger):
    schema = json.loads((ROOT / "harness" / "feature_schema.json").read_text())
    allowed = set(schema["properties"]["features"]["items"]["properties"])
    for f in ledger["features"]:
        assert not (set(f) - allowed), f"{f['id']}: unknown fields {set(f) - allowed}"


# ---------------------------------------------------------------- session logs
def test_every_referenced_session_has_a_log_file(ledger):
    on_disk = {p.name[:4] for p in (ROOT / "harness" / "sessions").glob("[0-9]" * 4 + "-*.md")}
    for f in ledger["features"]:
        for sid in f["sessions"]:
            assert sid in on_disk, f"{f['id']} references session {sid} with no log file"


def test_session_ids_are_contiguous_from_0001():
    ids = sorted(p.name[:4] for p in
                 (ROOT / "harness" / "sessions").glob("[0-9]" * 4 + "-*.md"))
    assert ids == [f"{i:04d}" for i in range(1, len(ids) + 1)], \
        f"session numbering has a gap: {ids}"


def test_session_logs_carry_the_required_sections():
    """A log without 'Carried forward' is a log the next session cannot use."""
    required = ["## Goal", "## Log", "## Outcome", "## Carried forward"]
    for path in (ROOT / "harness" / "sessions").glob("[0-9]" * 4 + "-*.md"):
        text = path.read_text()
        for section in required:
            assert section in text, f"{path.name} is missing {section!r}"


def test_progress_index_lists_every_session():
    progress = (ROOT / "harness" / "PROGRESS.md").read_text()
    for path in (ROOT / "harness" / "sessions").glob("[0-9]" * 4 + "-*.md"):
        assert path.name in progress, f"{path.name} missing from PROGRESS.md — run check"


# ---------------------------------------------------------------- harness docs
def test_agent_instructions_exist_and_claude_md_points_at_them():
    agents = ROOT / "AGENTS.md"
    claude = ROOT / "CLAUDE.md"
    assert agents.exists()
    assert claude.exists() and claude.read_text() == agents.read_text()
    text = agents.read_text()
    for section in ("## Repository structure", "## Tool permissions",
                    "## Verification gates", "## Known constraints"):
        assert section in text, f"AGENTS.md missing {section!r}"


def test_agents_md_permission_tiers_are_all_present():
    """The checklist requires allowed, restricted AND not-allowed to be explicit."""
    text = (ROOT / "AGENTS.md").read_text()
    for tier in ("**Allowed**", "**Restricted", "**Not allowed**"):
        assert tier in text


def test_planning_artifacts_exist():
    for name in ("PLAN.md", "IMPLEMENT.md", "HARNESS_CHECKLIST.md", "PROGRESS.md",
                 "features.json", "feature_schema.json", "features.lock"):
        assert (ROOT / "harness" / name).exists(), f"harness/{name} missing"


def test_removal_table_is_filled_in():
    """Every harness component must say what would make it unnecessary."""
    text = (ROOT / "harness" / "HARNESS_CHECKLIST.md").read_text()
    assert "Can be removed when" in text
    rows = [l for l in text.splitlines()
            if l.startswith("| ") and l.count("|") >= 4 and "---" not in l]
    body = [r for r in rows if "Can be removed when" not in r]
    assert len(body) >= 5, "removal table is a placeholder"
    for r in body:
        cells = [c.strip() for c in r.strip("|").split("|")]
        assert all(cells[:3]), f"empty cell in removal table row: {r}"


# ---------------------------------------------------------------- CLI
def test_harness_check_exits_zero():
    r = subprocess.run([sys.executable, "scripts/harness.py", "check"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_second_concurrent_feature_is_a_validation_error(ledger):
    """The one_at_a_time policy is enforced, not merely documented."""
    data = json.loads(json.dumps(ledger))
    assert H.validate(data) == []
    # Force two concurrently, regardless of how many are in progress right now.
    locked = [f for f in data["features"] if f["status"] == "locked"]
    assert len(locked) >= 2, "ledger has nothing left to start"
    for f in data["features"]:
        f["status"] = "locked" if f["status"] == "in_progress" else f["status"]
    locked[0]["status"] = "in_progress"
    locked[1]["status"] = "in_progress"
    assert any("one_at_a_time" in e for e in H.validate(data))


def test_ready_set_respects_dependencies(ledger):
    by_id = H.features_by_id(ledger)
    for f in H._ready(ledger):
        assert f["status"] == "locked"
        assert all(by_id[d]["status"] in ("done", "dropped") for d in f["depends_on"])


def test_done_refuses_when_verify_fails(tmp_path):
    """Definition of done is a passing gate, not a judgement call."""
    fake = {"id": "F-999", "verify": "exit 3"}
    assert H.run_verify(fake) == 3
