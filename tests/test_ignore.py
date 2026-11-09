"""Slice 0c tests: UTF-8 ignore loading, in-place pruned walk, symlink guard, tree rendering."""
from pathlib import Path

import pytest

from knowpiler.core import ignore


def test_load_ignore_patterns_seeds_from_gitignore_and_safety_net(tmp_path: Path) -> None:
    # Include non-ASCII UTF-8 comment to verify Windows cp1252 safety
    (tmp_path / ".gitignore").write_text("# कमेंट — résumé\ndist/\n*.log\n.venv/\n", encoding="utf-8")
    patterns = ignore.load_ignore_patterns(tmp_path)
    assert "dist/" in patterns
    assert "*.log" in patterns
    assert "node_modules/" in patterns
    assert ".knowpiler/" in patterns
    # .venv/ was in both .gitignore and STATIC_SAFETY_NET -- must appear only once
    assert patterns.count(".venv/") == 1


def test_existing_graphifyignore_takes_precedence_over_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored_by_git/\n", encoding="utf-8")
    (tmp_path / ".graphifyignore").write_text("only_graphify_rule/\n", encoding="utf-8")
    patterns = ignore.load_ignore_patterns(tmp_path)
    assert patterns == ["only_graphify_rule/"]


def test_write_graphifyignore_materializes_rules_to_disk(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    out = ignore.write_graphifyignore(tmp_path, extra_patterns=["data/", "build/"])
    assert out == tmp_path / ".graphifyignore"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "build/" in lines
    assert "data/" in lines
    assert "node_modules/" in lines
    assert lines.count("build/") == 1


def test_filtered_files_prunes_ignored_dirs_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    (tmp_path / "report.pdf").write_text("binary", encoding="utf-8")

    visited_dirs: list[str] = []
    real_walk = ignore.os.walk

    def tracking_walk(*args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(*args, **kwargs):
            visited_dirs.append(Path(dirpath).name)
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(ignore.os, "walk", tracking_walk)

    kept = ignore.filtered_files(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in kept] == ["src/main.py"]
    # Proof of in-place pruning: os.walk never descended into node_modules or pkg
    assert "node_modules" not in visited_dirs
    assert "pkg" not in visited_dirs


def test_filtered_files_and_render_tree_skip_symlink_loops(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    loop = tmp_path / "loop_self"
    try:
        loop.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not supported in this environment")

    kept = ignore.filtered_files(tmp_path)
    assert kept == [tmp_path / "app.py"]

    tree = ignore.render_tree(tmp_path)
    assert "app.py" in tree
    assert "loop_self" not in tree


def test_render_tree_orders_dirs_first_and_respects_ignores(tmp_path: Path) -> None:
    (tmp_path / "z_dir").mkdir()
    (tmp_path / "z_dir" / "inner.py").write_text("", encoding="utf-8")
    (tmp_path / "a_file.py").write_text("", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_text("", encoding="utf-8")

    tree = ignore.render_tree(tmp_path)
    lines = tree.splitlines()
    assert lines[1] == "├── z_dir"
    assert lines[2] == "│   └── inner.py"
    assert lines[3] == "└── a_file.py"
    assert "__pycache__" not in tree