"""
Deterministic, read-only candidate discovery for `knowpiler init` (C1, C13, C14, S1, S2).

Rules enforced here:
- Plain-data marker lookup with observation wording ("found package.json").
- Reads zero file contents and never calls an LLM or mutates a Manifest.
- Enforces disjoint inputs (C13) at suggestion time: once a folder has a
  code marker, we do not descend inside it for nested code candidates.
- Separate document pass so PDFs/DOCX/PPTX (ignored by STATIC_SAFETY_NET
  during code walks) are still surfaced as unchecked evidence suggestions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Tuple, Union

from knowpiler.core import ignore
from knowpiler.core.manifest import ROLES
from knowpiler.core.utils import clean_path, slugify

WORKSPACE_THRESHOLD = 6
DEFAULT_CAP = 20

# Plain-data signal -> observation text table (C1).
# Deliberately excludes "Makefile" so docs/ or scripts/ folders aren't treated as code roots.
CODE_MARKERS: Dict[str, str] = {
    ".git": "found .git",
    "pyproject.toml": "found pyproject.toml",
    "package.json": "found package.json",
    "requirements.txt": "found requirements.txt",
    "manage.py": "found manage.py",
    "Cargo.toml": "found Cargo.toml",
    "go.mod": "found go.mod",
    "pom.xml": "found pom.xml",
    "build.gradle": "found build.gradle",
    "composer.json": "found composer.json",
    "Gemfile": "found Gemfile",
    "CMakeLists.txt": "found CMakeLists.txt",
}

SKIP_DIRS: Set[str] = {
    ".git",
    ".knowpiler",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "graphify-out",
    ".pytest_cache",
    "dist",
    "build",
    "target",
}

# Generic words ignored during project-name token matching (S1) so "project-1"
# or "app-main" does not falsely match every "*-main" folder in a workspace.
STOP_TOKENS: Set[str] = {
    "project",
    "projects",
    "proj",
    "main",
    "master",
    "repo",
    "code",
    "app",
    "src",
    "dev",
    "test",
}

DOC_EXTENSIONS_TO_ROLE: Dict[str, str] = {
    ".pdf": "report",
    ".docx": "report",
    ".pptx": "presentation",
}


@dataclass(frozen=True)
class Suggestion:
    kind: Literal["input", "evidence"]
    path: str
    reason: str
    precheck: bool
    file_count: Optional[int] = None
    kind_hint: Optional[str] = None  # For kind == "input" (e.g. "code")
    role: Optional[str] = None       # For kind == "evidence" (e.g. "readme", "report")


@dataclass(frozen=True)
class SuggestResult:
    suggestions: Tuple[Suggestion, ...]
    note: Optional[str]
    skipped_symlinks: int
    truncated: int


def _meaningful_tokens(name: str) -> Set[str]:
    """Split a name into slugified whole tokens, dropping generic stop-words and digits."""
    if not name or not name.strip():
        return set()
    raw_tokens = [t for t in slugify(name).split("-") if t]
    return {t for t in raw_tokens if t not in STOP_TOKENS and not t.isdigit()}


def _matched_tokens(folder_name: str, project_tokens: Set[str]) -> List[str]:
    """Return sorted whole tokens shared between `folder_name` and `project_tokens`."""
    if not project_tokens:
        return []
    folder_tokens = {t for t in slugify(folder_name).split("-") if t}
    return sorted(folder_tokens & project_tokens)


def _detect_markers(dir_path: Path) -> Tuple[List[str], int]:
    """Return (list of marker observation strings, skipped_symlinks_count) for `dir_path`."""
    reasons: List[str] = []
    symlinks = 0
    try:
        entries = {e.name: e for e in dir_path.iterdir()}
    except OSError:
        return reasons, symlinks

    for marker, reason_text in CODE_MARKERS.items():
        entry = entries.get(marker)
        if entry is not None:
            if entry.is_symlink():
                symlinks += 1
                continue
            reasons.append(reason_text)
    return reasons, symlinks


def _find_root_readme(candidate_dir: Path) -> Optional[Path]:
    """Find a README file sitting directly at the root of `candidate_dir`."""
    readme_exts = ROLES["readme"].extensions
    try:
        entries = sorted(candidate_dir.iterdir(), key=lambda e: e.name.lower())
    except OSError:
        return None

    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            continue
        name_lower = entry.name.lower()
        suffix_lower = entry.suffix.lower()
        if name_lower == "readme" or (
            name_lower.startswith("readme.") and suffix_lower in readme_exts
        ):
            return entry
    return None


def suggest_from_folder(
    folder: Union[str, Path],
    project_name: str = "",
    max_depth: int = 3,
    cap: int = DEFAULT_CAP,
) -> SuggestResult:
    """Scan `folder` (up to `max_depth`) for candidate code inputs and evidence files."""
    cleaned = clean_path(str(folder))
    root = Path(cleaned).expanduser()
    if not root.exists() or not root.is_dir():
        return SuggestResult(
            suggestions=(),
            note=f"Folder does not exist or is not a directory: {root}",
            skipped_symlinks=0,
            truncated=0,
        )

    root = root.resolve()
    project_tokens = _meaningful_tokens(project_name)
    skipped_symlinks = 0

    # Pass 1: Candidate code roots (disjoint walk up to max_depth)
    raw_candidates: List[Tuple[Path, str, List[str]]] = []

    root_reasons, root_syms = _detect_markers(root)
    skipped_symlinks += root_syms

    if root_reasons:
        # Rule: If the dropped folder itself has a marker, it is the single candidate.
        matched = _matched_tokens(root.name, project_tokens)
        raw_candidates.append((root, ", ".join(root_reasons[:2]), matched))
    else:
        for dirpath, dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
            cur = Path(dirpath)
            rel_parts = cur.relative_to(root).parts
            depth = len(rel_parts)

            if depth > 0:
                reasons, syms = _detect_markers(cur)
                skipped_symlinks += syms
                if reasons:
                    matched = _matched_tokens(cur.name, project_tokens)
                    raw_candidates.append((cur, ", ".join(reasons[:2]), matched))
                    # Disjointness (C13): do not descend inside a candidate code root
                    dirnames[:] = []
                    continue

            if depth >= max_depth:
                dirnames[:] = []
                continue

            kept_dirs: List[str] = []
            for d in sorted(dirnames, key=str.lower):
                d_path = cur / d
                if d_path.is_symlink():
                    continue
                if d in SKIP_DIRS or d.startswith("."):
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs

    # Decide pre-check status (S1, S2, and single-candidate rule)
    single = len(raw_candidates) == 1
    matched_count = sum(1 for _, _, m in raw_candidates if m)
    allow_precheck = 1 <= matched_count <= WORKSPACE_THRESHOLD

    total_candidates = len(raw_candidates)
    truncated = max(0, total_candidates - cap)
    capped_candidates = raw_candidates[:cap]

    input_suggestions: List[Suggestion] = []
    readme_suggestions: List[Suggestion] = []
    seen_evidence_paths: Set[Path] = set()

    for cand_path, marker_reason, matched in capped_candidates:
        is_prechecked = (bool(matched) and allow_precheck) or single
        reason = marker_reason
        if matched:
            reason = f"{marker_reason} · name matches '{matched[0]}'"

        fcount = len(ignore.filtered_files(cand_path))
        input_suggestions.append(
            Suggestion(
                kind="input",
                path=str(cand_path),
                reason=reason,
                precheck=is_prechecked,
                file_count=fcount,
                kind_hint="code",
            )
        )

        # Suggest README only at the root of a candidate input
        readme_path = _find_root_readme(cand_path)
        if readme_path is not None:
            resolved_readme = readme_path.resolve()
            seen_evidence_paths.add(resolved_readme)
            readme_suggestions.append(
                Suggestion(
                    kind="evidence",
                    path=str(resolved_readme),
                    reason=f"found {readme_path.name} in {cand_path.name}",
                    precheck=is_prechecked,
                    role="readme",
                )
            )

    # Pass 2: Document discovery (PDF / DOCX / PPTX) + uniform symlink counting
    doc_suggestions: List[Suggestion] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        cur = Path(dirpath)
        depth = len(cur.relative_to(root).parts)
        kept: List[str] = []
        for d in sorted(dirnames, key=str.lower):
            if (cur / d).is_symlink():
                skipped_symlinks += 1
                continue
            if d not in SKIP_DIRS and not d.startswith("."):
                kept.append(d)
        dirnames[:] = kept if depth < max_depth else []

        for fname in sorted(filenames, key=str.lower):
            fpath = cur / fname
            if fpath.is_symlink():
                skipped_symlinks += 1
                continue
            ext = fpath.suffix.lower()
            if ext in DOC_EXTENSIONS_TO_ROLE:
                resolved_doc = fpath.resolve()
                if resolved_doc in seen_evidence_paths:
                    continue
                seen_evidence_paths.add(resolved_doc)
                doc_suggestions.append(
                    Suggestion(
                        kind="evidence",
                        path=str(resolved_doc),
                        reason=f"found {ext} document",
                        precheck=False,
                        role=DOC_EXTENSIONS_TO_ROLE[ext],
                    )
                )

    doc_truncated = max(0, len(doc_suggestions) - cap)
    doc_suggestions = doc_suggestions[:cap]
    truncated += doc_truncated
    all_suggestions = input_suggestions + readme_suggestions + doc_suggestions

    # Build note message (S2 + multi-match review hint)
    note: Optional[str] = None
    if total_candidates > WORKSPACE_THRESHOLD and not allow_precheck:
        note = (
            f"This looks like a workspace with many codebases ({total_candidates} found); "
            f"none pre-selected — pick the folders for this project."
        )
    elif total_candidates > 1 and not allow_precheck:
        note = f"Found {total_candidates} folders with codebase markers; select the ones to include."
    elif matched_count > 1 and allow_precheck:
        note = f"{matched_count} folders matched project name; review pre-selected items."

    return SuggestResult(
        suggestions=tuple(all_suggestions),
        note=note,
        skipped_symlinks=skipped_symlinks,
        truncated=truncated,
    )