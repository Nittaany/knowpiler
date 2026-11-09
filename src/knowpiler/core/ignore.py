"""
Parsing, materializing, and applying .graphifyignore with real Git-ignore
semantics via `pathspec` -- replaces both `rglob("*")` (which walked into
node_modules/.venv before filtering) and the separate `treewalk.py` module.

Load order:
  1. .graphifyignore exists at the project root -> use it as-is.
  2. Otherwise -> seed from .gitignore, then append a static binary/media
     safety net. The safety net matters even when an LLM-suggestion step
     is added later: the pipeline must never depend on a network call
     succeeding just to filter files.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional

import pathspec

STATIC_SAFETY_NET = [
    ".git/", ".knowpiler/", "node_modules/", "__pycache__/", ".venv/", "venv/",
    "graphify-out/", "*.lock",
    "*.png", "*.jpg", "*.jpeg", "*.webp", "*.ico", "*.svg",
    "*.pdf", "*.zip", "*.tar.gz",
]


def _dedupe_lines(lines: Iterable[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def load_ignore_patterns(project_root: Path) -> List[str]:
    """Load ignore rules from .graphifyignore if present, else .gitignore + safety net."""
    project_root = Path(project_root)
    graphifyignore = project_root / ".graphifyignore"
    if graphifyignore.exists():
        return [
            line.strip()
            for line in graphifyignore.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    patterns: List[str] = []
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        patterns.extend(gitignore.read_text(encoding="utf-8").splitlines())
    patterns.extend(STATIC_SAFETY_NET)
    return _dedupe_lines(patterns)


def write_graphifyignore(
    project_root: Path,
    extra_patterns: Optional[Iterable[str]] = None,
) -> Path:
    """Materialize the active ignore patterns to `{project_root}/.graphifyignore`."""
    project_root = Path(project_root)
    base_patterns = load_ignore_patterns(project_root)
    if extra_patterns:
        base_patterns.extend(extra_patterns)
    final_patterns = _dedupe_lines(base_patterns)

    target = project_root / ".graphifyignore"
    content = "\n".join(final_patterns) + ("\n" if final_patterns else "")
    target.write_text(content, encoding="utf-8")
    return target


def compile_spec(patterns: Iterable[str]) -> pathspec.PathSpec:
    """Compile gitignore-style patterns using pathspec 1.x's 'gitignore' engine."""
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _is_ignored_dir(rel_posix: str, spec: pathspec.PathSpec) -> bool:
    """Check both 'dir' and 'dir/' so directory-anchored rules ('node_modules/') match."""
    return spec.match_file(rel_posix) or spec.match_file(f"{rel_posix}/")


def filtered_files(
    project_root: Path,
    patterns: Optional[Iterable[str]] = None,
) -> List[Path]:
    """Walk project_root with in-place directory pruning and symlink loop protection."""
    root = Path(project_root)
    active_patterns = list(patterns) if patterns is not None else load_ignore_patterns(root)
    spec = compile_spec(active_patterns)
    kept: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        cur_dir = Path(dirpath)
        rel_dir = cur_dir.relative_to(root).as_posix()
        rel_prefix = "" if rel_dir == "." else f"{rel_dir}/"

        # Prune ignored and symlinked directories in-place so os.walk never enters them
        dirnames[:] = sorted(
            d for d in dirnames
            if not (cur_dir / d).is_symlink()
            and not _is_ignored_dir(f"{rel_prefix}{d}", spec)
        )

        for fname in sorted(filenames, key=str.lower):
            fpath = cur_dir / fname
            if fpath.is_symlink():
                continue
            rel_file = f"{rel_prefix}{fname}"
            if not spec.match_file(rel_file):
                kept.append(fpath)

    return kept


def render_tree(
    project_root: Path,
    patterns: Optional[Iterable[str]] = None,
    max_depth: int = 8,
) -> str:
    """Render an ASCII directory tree pruned by the same pathspec ignore rules."""
    root = Path(project_root)
    active_patterns = list(patterns) if patterns is not None else load_ignore_patterns(root)
    spec = compile_spec(active_patterns)
    lines: List[str] = [str(root)]

    def _walk(dir_path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            raw_entries = list(dir_path.iterdir())
        except PermissionError:
            return

        valid_entries: List[Path] = []
        for entry in raw_entries:
            if entry.is_symlink():
                continue
            rel = entry.relative_to(root).as_posix()
            if entry.is_dir():
                if not _is_ignored_dir(rel, spec):
                    valid_entries.append(entry)
            else:
                if not spec.match_file(rel):
                    valid_entries.append(entry)

        valid_entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

        for i, entry in enumerate(valid_entries):
            is_last = i == len(valid_entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 0)
    return "\n".join(lines)