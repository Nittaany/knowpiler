"""
Manifest v3 -- the pure collection artifact for one portfolio project.

Rules enforced here (D1-D2, C1-C13):
- Records only user-declared inputs (folders) and evidence (files).
- Never infers components, classifications, or boundaries.
- Core never prints or prompts: add_input, add_evidence, and remove_entry
  return structured Result and Problem objects that drive CLI, TUI, Web, and MCP.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError, field_validator

from knowpiler.core.utils import clean_path, slugify

SCHEMA_VERSION = 3


class ManifestError(ValueError):
    """Base class for manifest load/version errors."""


class ManifestNotFoundError(ManifestError):
    pass


class ManifestVersionError(ManifestError):
    pass


@dataclass(frozen=True)
class RoleSpec:
    role: str
    label: str
    extensions: frozenset[str]
    subtypes: Tuple[str, ...] = ()
    allow_bare_readme: bool = False

    @property
    def hint(self) -> str:
        if not self.extensions and not self.allow_bare_readme:
            return "any file type"
        parts = sorted(self.extensions)
        if self.allow_bare_readme:
            parts.append("README")
        return ", ".join(parts)


SUGGESTED_KINDS: Tuple[str, ...] = ("code", "docs", "hardware", "data", "other")

ROLES: Dict[str, RoleSpec] = {
    "readme": RoleSpec(
        role="readme",
        label="README",
        extensions=frozenset({".md", ".rst", ".txt", ".adoc", ".org"}),
        allow_bare_readme=True,
    ),
    "report": RoleSpec(
        role="report",
        label="Report",
        extensions=frozenset({".pdf", ".docx", ".md", ".txt"}),
        subtypes=(
            "final_report",
            "architecture_report",
            "functional_report",
            "research_report",
            "synopsis",
            "other",
        ),
    ),
    "research": RoleSpec(
        role="research",
        label="Research paper / doc",
        extensions=frozenset({".pdf", ".docx", ".md", ".txt"}),
    ),
    "presentation": RoleSpec(
        role="presentation",
        label="Presentation slides",
        extensions=frozenset({".pdf", ".pptx"}),
    ),
    "notes": RoleSpec(
        role="notes",
        label="Notes / checkpoint",
        extensions=frozenset({".md", ".txt", ".rst", ".adoc", ".org"}),
    ),
    "diagram": RoleSpec(
        role="diagram",
        label="Architecture diagram",
        extensions=frozenset({".pdf", ".svg", ".png", ".jpg", ".jpeg", ".webp"}),
    ),
    "other": RoleSpec(
        role="other",
        label="Other evidence",
        extensions=frozenset(),
    ),
}

ProblemCode = Literal[
    "not_found",
    "not_a_dir",
    "not_a_file",
    "unreadable",
    "wrong_type",
    "unknown_scope",
    "child_of_existing_input",
    "parent_of_existing_input",
    "replace_target_mismatch",
    "input_has_scoped_evidence",
]

ResultStatus = Literal[
    "added",
    "already_collected",
    "scope_extended",
    "replaced",
    "removed",
    "rejected",
]


@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    message: str
    path: Optional[str] = None
    conflicting_id: Optional[str] = None
    suggested_fixes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    ok: bool
    status: ResultStatus
    entry: Optional[Union["InputEntry", "EvidenceEntry"]] = None
    problems: Tuple[Problem, ...] = ()
    suggested_fixes: Tuple[str, ...] = ()


def check_evidence_path(role: str, path: str) -> Optional[str]:
    """Return a human-readable extension error for (role, path), or None if valid."""
    spec = ROLES.get(role)
    if spec is None or (not spec.extensions and not spec.allow_bare_readme):
        return None  # "other" or custom user role accepts any extension

    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in spec.extensions:
        return None
    if spec.allow_bare_readme and suffix == "":
        return None

    return (
        f"{role}: '{p.name}' is type '{suffix or 'none'}' "
        f"but only {spec.hint} is accepted"
    )


def compute_file_fingerprint(path: Path) -> Tuple[int, str]:
    """Stream file in 1 MB chunks and return (size_in_bytes, sha256_hex)."""
    h, size = hashlib.sha256(), 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(prefix: str, existing_ids: List[str]) -> str:
    max_num = 0
    for item_id in existing_ids:
        if item_id.startswith(f"{prefix}-"):
            tail = item_id[len(prefix) + 1 :]
            if tail.isdigit():
                max_num = max(max_num, int(tail))
    return f"{prefix}-{max_num + 1}"


class InputEntry(BaseModel):
    id: str
    path: str
    kind: str = "code"
    label: str
    added_at: str = Field(default_factory=_utc_now)

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        return clean_path(v)


class EvidenceEntry(BaseModel):
    id: str
    path: str
    role: str
    subtype: Optional[str] = None
    scope: List[str] = []
    size: int
    sha256: str
    added_at: str = Field(default_factory=_utc_now)

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        return clean_path(v)


class Manifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    project: str
    staging_dir: str
    created_at: str = Field(default_factory=_utc_now)
    inputs: List[InputEntry] = []
    evidence: List[EvidenceEntry] = []

    def save(self, path: Optional[Path] = None) -> Path:
        target = Path(path) if path else (Path(self.staging_dir) / "manifest.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.model_dump(), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".manifest-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_name, target)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return target

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ManifestError(f"{path} is not valid JSON ({e})") from e

        if not isinstance(data, dict):
            raise ManifestError(f"{path} must contain a JSON object, got {type(data).__name__}")

        version = data.get("schema_version", 1)
        project = data.get("project", "<project>")
        if version < SCHEMA_VERSION:
            raise ManifestVersionError(
                f"{path} was made by an older knowpiler (manifest schema {version}; "
                f"this version needs {SCHEMA_VERSION}). Re-run `knowpiler init {project}` to rebuild it."
            )
        if version > SCHEMA_VERSION:
            raise ManifestVersionError(
                f"{path} was made by a newer knowpiler (manifest schema {version}); please upgrade knowpiler."
            )
        try:
            return cls(**data)
        except ValidationError as e:
            raise ManifestError(f"{path} failed schema validation: {e}") from e


def staging_dir_for(project: str, storage_root: str) -> Path:
    """The single place that decides where a project's workspace folder lives."""
    return Path(storage_root) / slugify(project)


def manifest_path_for(project: str, storage_root: str) -> Path:
    return staging_dir_for(project, storage_root) / "manifest.json"


def init_manifest(project: str, storage_root: str, save: bool = False) -> Manifest:
    """Create a fresh v3 Manifest (in-memory draft by default; saves if save=True)."""
    manifest = Manifest(
        project=project,
        staging_dir=str(staging_dir_for(project, storage_root)),
    )
    if save:
        manifest.save()
    return manifest


def load_manifest(project: str, storage_root: str) -> Manifest:
    """Load a project's manifest by name."""
    path = manifest_path_for(project, storage_root)
    if not path.exists():
        raise ManifestNotFoundError(
            f"No manifest for project '{project}' (looked in {path}). "
            f"Run `knowpiler init {project}` first."
        )
    return Manifest.load(path)


def add_input(
    manifest: Manifest,
    path: Union[str, Path],
    kind: str = "code",
    label: Optional[str] = None,
    replace_id: Optional[str] = None,
) -> Result:
    """Validate and add a folder input to `manifest`, enforcing disjoint roots (C13)."""
    cleaned = clean_path(str(path))
    candidate = Path(cleaned).expanduser()

    if not candidate.exists():
        prob = Problem(
            code="not_found",
            message=f"Folder does not exist: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    if not candidate.is_dir():
        prob = Problem(
            code="not_a_dir",
            message=f"Path is not a directory: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    if not os.access(candidate, os.R_OK):
        prob = Problem(
            code="unreadable",
            message=f"Directory is not readable: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    resolved = candidate.resolve()
    chosen_label = (label or resolved.name or str(resolved)).strip()

    target: Optional[InputEntry] = None
    if replace_id is not None:
        target = next((i for i in manifest.inputs if i.id == replace_id), None)
        if target is None:
            prob = Problem(
                code="not_found",
                message=f"No input '{replace_id}' to replace",
            )
            return Result(ok=False, status="rejected", problems=(prob,))
        if not resolved.is_relative_to(Path(target.path).resolve()):
            prob = Problem(
                code="replace_target_mismatch",
                message=f"'{resolved.name}' is not inside '{target.label}', so it cannot replace it.",
                path=str(resolved),
                conflicting_id=target.id,
                suggested_fixes=("skip",),
            )
            return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=("skip",))

    # Check duplicates and parent/child overlaps against all other inputs (Rule 1 / C13)
    for existing in manifest.inputs:
        if existing is target:
            continue
        existing_resolved = Path(existing.path).resolve()
        if resolved == existing_resolved:
            return Result(ok=True, status="already_collected", entry=existing)

        if resolved.is_relative_to(existing_resolved):
            fixes = ("replace_existing", "skip")
            prob = Problem(
                code="child_of_existing_input",
                message=(
                    f"'{resolved.name}' is inside existing input '{existing.label}' ({existing.id}). "
                    f"Replace '{existing.label}' with '{resolved.name}', or skip."
                ),
                path=str(resolved),
                conflicting_id=existing.id,
                suggested_fixes=fixes,
            )
            return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=fixes)

        if existing_resolved.is_relative_to(resolved):
            fixes = ("skip",)
            prob = Problem(
                code="parent_of_existing_input",
                message=(
                    f"'{resolved.name}' contains existing input '{existing.label}' ({existing.id}). "
                    f"Add specific codebase folders, not their parent."
                ),
                path=str(resolved),
                conflicting_id=existing.id,
                suggested_fixes=fixes,
            )
            return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=fixes)

    if target is not None:
        target.path = str(resolved)
        target.kind = kind.strip() or "code"
        target.label = chosen_label
        return Result(ok=True, status="replaced", entry=target)

    new_id = _next_id("in", [i.id for i in manifest.inputs])
    entry = InputEntry(
        id=new_id,
        path=str(resolved),
        kind=kind.strip() or "code",
        label=chosen_label,
    )
    manifest.inputs.append(entry)
    return Result(ok=True, status="added", entry=entry)


def add_evidence(
    manifest: Manifest,
    path: Union[str, Path],
    role: str = "report",
    scope: Optional[List[str]] = None,
    subtype: Optional[str] = None,
) -> Result:
    """Validate, fingerprint, and add an evidence file to `manifest` (C3, C12, Rule 3)."""
    cleaned = clean_path(str(path))
    candidate = Path(cleaned).expanduser()

    if not candidate.exists():
        prob = Problem(
            code="not_found",
            message=f"File does not exist: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    if not candidate.is_file():
        prob = Problem(
            code="not_a_file",
            message=f"Path is not a file: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    if not os.access(candidate, os.R_OK):
        prob = Problem(
            code="unreadable",
            message=f"File is not readable: {candidate}",
            path=str(candidate),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    role_key = role.strip().lower()
    type_problem = check_evidence_path(role_key, str(candidate))
    if type_problem:
        fixes = ("retry", "save_as_other", "skip")
        prob = Problem(
            code="wrong_type",
            message=type_problem,
            path=str(candidate),
            suggested_fixes=fixes,
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=fixes)

    resolved = candidate.resolve()

    # Validate or auto-infer scope (Rule 3)
    known_input_ids = {i.id for i in manifest.inputs}
    if scope is not None:
        unknown = [sid for sid in scope if sid not in known_input_ids]
        if unknown:
            prob = Problem(
                code="unknown_scope",
                message=f"Unknown input scope ID(s): {', '.join(unknown)}",
                path=str(resolved),
                suggested_fixes=("retry", "skip"),
            )
            return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)
        resolved_scope = list(dict.fromkeys(scope))
    else:
        resolved_scope = [
            inp.id
            for inp in manifest.inputs
            if resolved.is_relative_to(Path(inp.path).resolve())
        ]

    # Duplicate check by resolved path (C3): same scope = no-op, new scope = extend scope
    for existing in manifest.evidence:
        if Path(existing.path).resolve() == resolved:
            new_scopes = [sid for sid in resolved_scope if sid not in existing.scope]
            if not new_scopes:
                return Result(ok=True, status="already_collected", entry=existing)
            existing.scope.extend(new_scopes)
            return Result(ok=True, status="scope_extended", entry=existing)

    try:
        size, sha256 = compute_file_fingerprint(resolved)
    except OSError as e:
        prob = Problem(
            code="unreadable",
            message=f"Could not read {resolved.name}: {e}",
            path=str(resolved),
            suggested_fixes=("retry", "skip"),
        )
        return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=prob.suggested_fixes)

    new_id = _next_id("ev", [e.id for e in manifest.evidence])
    entry = EvidenceEntry(
        id=new_id,
        path=str(resolved),
        role=role_key,
        subtype=subtype,
        scope=resolved_scope,
        size=size,
        sha256=sha256,
    )
    manifest.evidence.append(entry)
    return Result(ok=True, status="added", entry=entry)


def remove_entry(manifest: Manifest, entry_id: str, cascade: bool = False) -> Result:
    """Remove an input or evidence entry by ID, guarding exclusively-scoped evidence."""
    for i, inp in enumerate(manifest.inputs):
        if inp.id == entry_id:
            orphans = [e for e in manifest.evidence if e.scope == [entry_id]]
            if orphans and not cascade:
                orphan_ids = ", ".join(e.id for e in orphans)
                fixes = ("remove_with_evidence", "skip")
                prob = Problem(
                    code="input_has_scoped_evidence",
                    message=(
                        f"Input '{entry_id}' has evidence scoped only to it ({orphan_ids}). "
                        f"Removing it alone would widen their scope to the whole project."
                    ),
                    conflicting_id=entry_id,
                    suggested_fixes=fixes,
                )
                return Result(ok=False, status="rejected", problems=(prob,), suggested_fixes=fixes)

            removed = manifest.inputs.pop(i)
            if orphans and cascade:
                orphan_set = {e.id for e in orphans}
                manifest.evidence = [e for e in manifest.evidence if e.id not in orphan_set]

            for ev in manifest.evidence:
                if entry_id in ev.scope:
                    ev.scope.remove(entry_id)
            return Result(ok=True, status="removed", entry=removed)

    for i, ev in enumerate(manifest.evidence):
        if ev.id == entry_id:
            removed = manifest.evidence.pop(i)
            return Result(ok=True, status="removed", entry=removed)

    prob = Problem(
        code="not_found",
        message=f"No input or evidence entry with id '{entry_id}'",
    )
    return Result(ok=False, status="rejected", problems=(prob,))