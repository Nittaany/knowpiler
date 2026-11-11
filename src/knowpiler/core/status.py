"""
Read-only project status (C7): what is collected, what is missing, what drifted.

Never mutates the manifest, never prompts, never prints. Findings use stable
codes so CLI, TUI, web, and MCP can all render them their own way.
Collection validity is not processing readiness: `ready_for_normalize` is the
only readiness signal here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from knowpiler.core.manifest import ROLES, Manifest, compute_file_fingerprint

# Placeholder until `normalize` / convert.py owns the real list. "" = bare README.
CONVERTIBLE_EXTENSIONS = frozenset(
    {"", ".md", ".txt", ".rst", ".adoc", ".org", ".pdf", ".docx", ".pptx"}
)


@dataclass(frozen=True)
class Finding:
    level: Literal["info", "warn"]
    code: str
    message: str
    ref: Optional[str] = None  # input/evidence id this finding is about


@dataclass(frozen=True)
class StatusReport:
    n_inputs: int
    n_evidence: int
    findings: Tuple[Finding, ...]

    @property
    def ready_for_normalize(self) -> bool:
        return self.n_inputs > 0 and not any(f.code == "input_missing" for f in self.findings)


def _drifted(path: Path, size: int, sha256: str) -> bool:
    """Size first (free); re-hash only when the size matches."""
    if path.stat().st_size != size:
        return True
    return compute_file_fingerprint(path)[1] != sha256


def get_status(manifest: Manifest) -> StatusReport:
    findings: List[Finding] = []
    inputs_by_id = {i.id: i for i in manifest.inputs}

    if not manifest.inputs:
        findings.append(Finding(
            "warn", "no_inputs",
            "Nothing to analyze yet: normalize needs at least one input folder.",
        ))
    for inp in manifest.inputs:
        if not Path(inp.path).is_dir():
            findings.append(Finding(
                "warn", "input_missing",
                f"Input '{inp.label}' ({inp.id}) no longer exists at {inp.path}.", inp.id,
            ))

    if not any(e.role == "readme" for e in manifest.evidence):
        findings.append(Finding(
            "info", "no_readme",
            "No README collected: README-derived claims will be [UNKNOWN].",
        ))

    for ev in manifest.evidence:
        p = Path(ev.path)

        if ev.role not in ROLES:
            findings.append(Finding(
                "warn", "unknown_role",
                f"'{p.name}' ({ev.id}) has role '{ev.role}', which is not a known role.", ev.id,
            ))
        if p.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
            findings.append(Finding(
                "info", "unsupported_for_normalize",
                f"'{p.name}' ({ev.id}) is collected, but normalize will skip type '{p.suffix.lower()}'.",
                ev.id,
            ))
        for sid in ev.scope:
            inp = inputs_by_id.get(sid)
            if inp is None:
                findings.append(Finding("warn", "scope_dangling",
                    f"'{p.name}' ({ev.id}) is scoped to {sid}, which no longer exists.", ev.id))
            elif not p.resolve().is_relative_to(Path(inp.path).resolve()):
                findings.append(Finding("info", "scope_outside_input",
                    f"'{p.name}' ({ev.id}) is scoped to {sid} but lives outside it (fine if intentional).", ev.id))

        if not p.is_file():
            findings.append(Finding(
                "warn", "evidence_missing",
                f"'{p.name}' ({ev.id}) no longer exists at {ev.path}.", ev.id,
            ))
            continue
        try:
            if _drifted(p, ev.size, ev.sha256):
                findings.append(Finding(
                    "warn", "evidence_changed",
                    f"'{p.name}' ({ev.id}) changed since it was collected.", ev.id,
                ))
        except OSError as e:
            findings.append(Finding(
                "warn", "evidence_unreadable",
                f"Could not read '{p.name}' ({ev.id}): {e}", ev.id,
            ))

    return StatusReport(len(manifest.inputs), len(manifest.evidence), tuple(findings))