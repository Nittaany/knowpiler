"""Step 2a tests: deterministic candidate discovery, token matching (S1), workspace cap (S2)."""
from pathlib import Path

import pytest

from knowpiler.core import discover


def test_dropped_folder_with_marker_is_single_candidate_and_does_not_descend(tmp_path: Path) -> None:
    repo = tmp_path / "lms-app"
    nested = repo / "packages" / "subpkg"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("# LMS\n", encoding="utf-8")
    # Nested package.json inside repo must NOT become a second candidate (C13)
    (nested / "package.json").write_text("{}\n", encoding="utf-8")

    res = discover.suggest_from_folder(repo, project_name="LMS")
    inputs = [s for s in res.suggestions if s.kind == "input"]
    readmes = [s for s in res.suggestions if s.role == "readme"]

    assert len(inputs) == 1
    assert inputs[0].path == str(repo.resolve())
    assert inputs[0].precheck is True
    assert inputs[0].kind_hint == "code"
    assert inputs[0].role is None
    assert "found pyproject.toml" in inputs[0].reason
    assert "name matches 'lms'" in inputs[0].reason
    assert inputs[0].file_count == 4  # pyproject.toml, main.py, README.md, packages/subpkg/package.json

    assert len(readmes) == 1
    assert readmes[0].precheck is True


def test_single_candidate_is_prechecked_even_when_project_name_has_no_tokens(tmp_path: Path) -> None:
    repo = tmp_path / "gesture-interface"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    # Makefile inside docs/ must NOT be treated as a code marker
    (docs / "Makefile").write_text("html:\n\tsphinx-build\n", encoding="utf-8")

    res = discover.suggest_from_folder(repo, project_name="project-1")
    inputs = [s for s in res.suggestions if s.kind == "input"]
    assert len(inputs) == 1
    assert inputs[0].precheck is True
    assert inputs[0].kind_hint == "code"


def test_whole_token_matching_rejects_substrings_and_prechecks_all_matches(tmp_path: Path) -> None:
    ws = tmp_path / "Projects"
    for name in ("lms-frontend", "lms-backend", "lms-mobile", "calms-app", "hotel-system"):
        d = ws / name
        d.mkdir(parents=True)
        (d / "package.json").write_text("{}\n", encoding="utf-8")

    res = discover.suggest_from_folder(ws, project_name="LMS")
    inputs = {Path(s.path).name: s for s in res.suggestions if s.kind == "input"}

    assert len(inputs) == 5
    # Whole-token "lms" matches all 3 lms-* folders
    assert inputs["lms-frontend"].precheck is True
    assert inputs["lms-backend"].precheck is True
    assert inputs["lms-mobile"].precheck is True
    # "calms-app" contains substring "lms" but not whole token "lms" -> False!
    assert inputs["calms-app"].precheck is False
    assert inputs["hotel-system"].precheck is False
    assert res.note == "3 folders matched project name; review pre-selected items."


def test_stop_tokens_prevent_false_matches_on_generic_names(tmp_path: Path) -> None:
    container = tmp_path / "LMS-pankaj"
    for name in ("Shoonyaveer-lms-backend-main", "ShoonyaVeer-LMS-main"):
        d = container / name
        d.mkdir(parents=True)
        (d / "package.json").write_text("{}\n", encoding="utf-8")

    # Project named "project-1" or "project-main" has only stop tokens -> no false precheck
    res = discover.suggest_from_folder(container, project_name="project-1")
    inputs = [s for s in res.suggestions if s.kind == "input"]
    assert len(inputs) == 2
    assert all(not s.precheck for s in inputs)
    assert res.note is not None and "Found 2 folders" in res.note


def test_workspace_with_many_unmatched_repos_triggers_workspace_note_and_cap(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    for i in range(1, 10):
        d = ws / f"service-{i:02d}"
        d.mkdir(parents=True)
        (d / "pyproject.toml").write_text("", encoding="utf-8")

    res = discover.suggest_from_folder(ws, project_name="unrelated", cap=7)
    inputs = [s for s in res.suggestions if s.kind == "input"]
    assert len(inputs) == 7
    assert res.truncated == 2
    assert all(not s.precheck for s in inputs)
    assert res.note is not None and "workspace with many codebases (9 found)" in res.note


def test_document_pass_surfaces_pdfs_unchecked_even_though_safety_net_ignores_pdf(tmp_path: Path) -> None:
    repo = tmp_path / "my-repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    (docs / "architecture.pdf").write_bytes(b"%PDF-1.4")
    (docs / "slides.pptx").write_bytes(b"pptx")

    res = discover.suggest_from_folder(repo, project_name="my-repo")
    ev = {Path(s.path).name: s for s in res.suggestions if s.kind == "evidence"}

    assert "architecture.pdf" in ev
    assert ev["architecture.pdf"].precheck is False
    assert ev["architecture.pdf"].role == "report"
    assert "slides.pptx" in ev
    assert ev["slides.pptx"].precheck is False
    assert ev["slides.pptx"].role == "presentation"


def test_symlinks_are_skipped_and_counted_and_empty_folder_is_normal(tmp_path: Path) -> None:
    empty = tmp_path / "empty_folder"
    empty.mkdir()
    res_empty = discover.suggest_from_folder(empty, project_name="demo")
    assert res_empty.suggestions == ()
    assert res_empty.note is None

    ws = tmp_path / "sym_ws"
    real_dir = ws / "real"
    real_dir.mkdir(parents=True)
    (real_dir / "package.json").write_text("{}", encoding="utf-8")
    sym_dir = ws / "linked"
    try:
        sym_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not supported")

    res_sym = discover.suggest_from_folder(ws, project_name="demo")
    inputs = [s for s in res_sym.suggestions if s.kind == "input"]
    assert len(inputs) == 1
    assert res_sym.skipped_symlinks == 1