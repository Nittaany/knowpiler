"""Step 2b tests: readiness, hash drift, stranded scope, unknown roles."""
from pathlib import Path

from knowpiler.core import manifest as mf
from knowpiler.core.status import get_status


def _codes(report) -> set:
    return {f.code for f in report.findings}


def test_empty_project_is_valid_but_not_ready(tmp_path: Path) -> None:
    m = mf.init_manifest("p", str(tmp_path / "store"))
    r = get_status(m)
    assert (r.n_inputs, r.n_evidence) == (0, 0)
    assert _codes(r) == {"no_inputs", "no_readme"}
    assert r.ready_for_normalize is False


def test_clean_project_is_ready_with_no_warnings(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "README.md").write_text("hi", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_input(m, fe)
    mf.add_evidence(m, fe / "README.md", role="readme")
    r = get_status(m)
    assert r.findings == ()
    assert r.ready_for_normalize is True


def test_hash_catches_same_size_edit_and_size_catches_growth(tmp_path: Path) -> None:
    same = tmp_path / "same.md"
    grow = tmp_path / "grow.md"
    same.write_text("aaaa", encoding="utf-8")
    grow.write_text("aaaa", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_evidence(m, same, role="notes")
    mf.add_evidence(m, grow, role="notes")

    same.write_text("aaab", encoding="utf-8")      # same size, different bytes
    grow.write_text("aaaaaaaa", encoding="utf-8")  # different size
    changed = [f for f in get_status(m).findings if f.code == "evidence_changed"]
    assert {f.ref for f in changed} == {"ev-1", "ev-2"}


def test_missing_evidence_and_missing_input(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    fe.mkdir()
    doc = tmp_path / "notes.md"
    doc.write_text("x", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_input(m, fe)
    mf.add_evidence(m, doc, role="notes")

    doc.unlink()
    fe.rmdir()
    r = get_status(m)
    assert {"evidence_missing", "input_missing"} <= _codes(r)
    assert r.ready_for_normalize is False


def test_replace_can_leave_scoped_evidence_outside_its_input(tmp_path: Path) -> None:
    parent = tmp_path / "LMS"
    sub = parent / "frontend"
    sub.mkdir(parents=True)
    (parent / "README.md").write_text("root readme", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_input(m, parent)                                   # in-1
    mf.add_evidence(m, parent / "README.md", role="readme")   # scoped to in-1
    assert mf.add_input(m, sub, replace_id="in-1").ok         # in-1 is now the child

    outside = [f for f in get_status(m).findings if f.code == "scope_outside_input"]
    assert [f.ref for f in outside] == ["ev-1"]
    assert all(f.level == "info" for f in outside)


def test_shared_doc_scoped_to_two_inputs_gives_no_warnings(tmp_path: Path) -> None:
    fe, be = tmp_path / "frontend", tmp_path / "backend"
    fe.mkdir()
    be.mkdir()
    shared = tmp_path / "shared.md"
    shared.write_text("spec", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_input(m, fe)
    mf.add_input(m, be)
    mf.add_evidence(m, shared, role="notes", scope=["in-1", "in-2"])

    assert not [f for f in get_status(m).findings if f.level == "warn"]


def test_scope_pointing_at_a_vanished_input_is_a_warning(tmp_path: Path) -> None:
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "README.md").write_text("hi", encoding="utf-8")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_input(m, fe)
    mf.add_evidence(m, fe / "README.md", role="readme")
    m.inputs.clear()  # simulates a hand-edited manifest; remove_entry would never do this

    dangling = [f for f in get_status(m).findings if f.code == "scope_dangling"]
    assert [f.ref for f in dangling] == ["ev-1"]
    assert dangling[0].level == "warn"


def test_unknown_role_and_unsupported_type_are_reported(tmp_path: Path) -> None:
    typo = tmp_path / "a.md"
    img = tmp_path / "arch.png"
    typo.write_text("x", encoding="utf-8")
    img.write_bytes(b"\x89PNG")
    m = mf.init_manifest("p", str(tmp_path / "store"))
    mf.add_evidence(m, typo, role="reprot")  # custom role accepts any extension
    mf.add_evidence(m, img, role="diagram")

    r = get_status(m)
    assert {"unknown_role", "unsupported_for_normalize"} <= _codes(r)
    levels = {f.code: f.level for f in r.findings}
    assert levels["unsupported_for_normalize"] == "info"