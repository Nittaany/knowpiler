"""Step 1 tests: Manifest v3, ROLES table, disjoint inputs (C13), evidence scope & sha256."""
import hashlib
import json
from pathlib import Path

import pytest

from knowpiler.core import manifest as mf


def test_schema_version_is_3() -> None:
    assert mf.SCHEMA_VERSION == 3


def test_empty_manifest_is_valid_and_round_trips(tmp_path: Path) -> None:
    m = mf.init_manifest("Café Ünï", str(tmp_path / "store"), save=True)
    assert m.inputs == []
    assert m.evidence == []
    loaded = mf.load_manifest("Café Ünï", str(tmp_path / "store"))
    assert loaded == m


def test_missing_old_and_corrupt_manifests_raise_manifest_error(tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    with pytest.raises(mf.ManifestNotFoundError, match="knowpiler init ghost"):
        mf.load_manifest("ghost", store)

    old_path = mf.manifest_path_for("old", store)
    old_path.parent.mkdir(parents=True)
    old_path.write_text(
        json.dumps({"schema_version": 2, "project": "old"}),
        encoding="utf-8",
    )
    with pytest.raises(mf.ManifestVersionError, match="knowpiler init old"):
        mf.load_manifest("old", store)

    list_path = mf.manifest_path_for("list-json", store)
    list_path.parent.mkdir(parents=True)
    list_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="JSON object"):
        mf.load_manifest("list-json", store)

    bad_schema = mf.manifest_path_for("bad-schema", store)
    bad_schema.parent.mkdir(parents=True)
    bad_schema.write_text(
        json.dumps({"schema_version": 3, "project": "bad-schema", "inputs": "not-a-list"}),
        encoding="utf-8",
    )
    with pytest.raises(mf.ManifestError, match="schema validation"):
        mf.load_manifest("bad-schema", store)


def test_disjoint_inputs_same_folder_is_noop(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    m = mf.init_manifest("lms", str(tmp_path / "store"))

    r1 = mf.add_input(m, f"'{backend}'", kind="code", label="backend")
    assert r1.ok and r1.status == "added"
    assert r1.entry.id == "in-1"

    r2 = mf.add_input(m, backend)
    assert r2.ok and r2.status == "already_collected"
    assert len(m.inputs) == 1


def test_disjoint_inputs_parent_then_child_offers_replace(tmp_path: Path) -> None:
    parent = tmp_path / "LMS-pankaj"
    frontend = parent / "frontend"
    backend = parent / "backend"
    unrelated = tmp_path / "unrelated"
    frontend.mkdir(parents=True)
    backend.mkdir(parents=True)
    unrelated.mkdir(parents=True)

    m = mf.init_manifest("lms", str(tmp_path / "store"))
    assert mf.add_input(m, parent).ok

    # Adding child after parent is rejected and offers replace_existing
    r_child = mf.add_input(m, frontend)
    assert not r_child.ok
    assert r_child.problems[0].code == "child_of_existing_input"
    assert r_child.problems[0].conflicting_id == "in-1"
    assert "replace_existing" in r_child.suggested_fixes

    # Unknown replace_id is rejected
    r_bad_id = mf.add_input(m, frontend, replace_id="in-99")
    assert not r_bad_id.ok
    assert r_bad_id.problems[0].code == "not_found"

    # Replacing with a folder NOT inside target is rejected
    r_mismatch = mf.add_input(m, unrelated, replace_id="in-1")
    assert not r_mismatch.ok
    assert r_mismatch.problems[0].code == "replace_target_mismatch"

    # Replacing parent with child succeeds, allowing sibling backend to be added next
    r_replace = mf.add_input(m, frontend, replace_id="in-1")
    assert r_replace.ok and r_replace.status == "replaced"
    assert m.inputs[0].path == str(frontend.resolve())

    r_backend = mf.add_input(m, backend)
    assert r_backend.ok and r_backend.status == "added"
    assert [i.label for i in m.inputs] == ["frontend", "backend"]


def test_disjoint_inputs_child_then_parent_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "LMS-pankaj"
    frontend = parent / "frontend"
    frontend.mkdir(parents=True)

    m = mf.init_manifest("lms", str(tmp_path / "store"))
    assert mf.add_input(m, frontend).ok

    r_parent = mf.add_input(m, parent)
    assert not r_parent.ok
    assert r_parent.problems[0].code == "parent_of_existing_input"
    assert r_parent.suggested_fixes == ("skip",)
    assert len(m.inputs) == 1


def test_evidence_auto_scope_and_two_readmes(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    be = tmp_path / "backend"
    fe.mkdir()
    be.mkdir()
    fe_readme = fe / "README.md"
    be_readme = be / "README"  # bare README without extension
    ext_report = tmp_path / "report.pdf"
    fe_readme.write_text("# Frontend\n", encoding="utf-8")
    be_readme.write_text("# Backend\n", encoding="utf-8")
    ext_report.write_bytes(b"%PDF-1.4 dummy content")

    m = mf.init_manifest("lms", str(tmp_path / "store"))
    mf.add_input(m, fe, label="frontend")  # in-1
    mf.add_input(m, be, label="backend")   # in-2

    r1 = mf.add_evidence(m, fe_readme, role="readme")
    r2 = mf.add_evidence(m, be_readme, role="readme")
    r3 = mf.add_evidence(m, ext_report, role="report", subtype="architecture_report")

    assert r1.ok and r1.entry.scope == ["in-1"]
    assert r2.ok and r2.entry.scope == ["in-2"]
    assert r3.ok and r3.entry.scope == []  # outside inputs -> whole project
    assert r3.entry.sha256 == hashlib.sha256(b"%PDF-1.4 dummy content").hexdigest()
    assert r3.entry.size == len(b"%PDF-1.4 dummy content")


def test_duplicate_evidence_same_scope_noop_and_new_scope_extends(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    be = tmp_path / "backend"
    fe.mkdir()
    be.mkdir()
    shared_doc = tmp_path / "shared_spec.md"
    shared_doc.write_text("spec", encoding="utf-8")

    m = mf.init_manifest("lms", str(tmp_path / "store"))
    mf.add_input(m, fe)  # in-1
    mf.add_input(m, be)  # in-2

    r1 = mf.add_evidence(m, shared_doc, role="report", scope=["in-1"])
    assert r1.ok and r1.status == "added"

    # Same path + same scope -> already_collected
    r2 = mf.add_evidence(m, shared_doc, role="report", scope=["in-1"])
    assert r2.ok and r2.status == "already_collected"
    assert len(m.evidence) == 1

    # Same path + different scope -> extends scope list
    r3 = mf.add_evidence(m, shared_doc, role="report", scope=["in-2"])
    assert r3.ok and r3.status == "scope_extended"
    assert m.evidence[0].scope == ["in-1", "in-2"]


def test_wrong_extension_returns_save_as_other_fix(tmp_path: Path) -> None:
    slides = tmp_path / "deck.pptx"
    slides.write_bytes(b"pptx-bytes")
    m = mf.init_manifest("lms", str(tmp_path / "store"))

    res = mf.add_evidence(m, slides, role="report")
    assert not res.ok
    assert res.problems[0].code == "wrong_type"
    assert res.suggested_fixes == ("retry", "save_as_other", "skip")

    # Saving under role="other" succeeds for any extension
    res_other = mf.add_evidence(m, slides, role="other")
    assert res_other.ok and res_other.status == "added"


def test_remove_entry_guards_orphan_evidence_and_supports_cascade(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    be = tmp_path / "backend"
    fe.mkdir()
    be.mkdir()
    fe_readme = fe / "README.md"
    shared = tmp_path / "shared.md"
    fe_readme.write_text("fe", encoding="utf-8")
    shared.write_text("shared", encoding="utf-8")

    m = mf.init_manifest("lms", str(tmp_path / "store"))
    mf.add_input(m, fe)  # in-1
    mf.add_input(m, be)  # in-2
    mf.add_evidence(m, fe_readme, role="readme")  # ev-1 scoped only to in-1
    mf.add_evidence(m, shared, role="notes", scope=["in-1", "in-2"])  # ev-2 shared

    # Without cascade, removing in-1 is blocked because ev-1 would lose its only scope
    res_blocked = mf.remove_entry(m, "in-1", cascade=False)
    assert not res_blocked.ok
    assert res_blocked.problems[0].code == "input_has_scoped_evidence"
    assert "remove_with_evidence" in res_blocked.suggested_fixes
    assert len(m.inputs) == 2

    # With cascade=True, in-1 and its exclusive orphan (ev-1) are removed,
    # while ev-2 stays and narrows its scope to ["in-2"]
    res_cascade = mf.remove_entry(m, "in-1", cascade=True)
    assert res_cascade.ok and res_cascade.status == "removed"
    assert [i.id for i in m.inputs] == ["in-2"]
    assert [e.id for e in m.evidence] == ["ev-2"]
    assert m.evidence[0].scope == ["in-2"]