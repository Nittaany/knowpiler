"""
knowpiler CLI -- the interface layer.

This file's only job is: collect input from a terminal (via InquirerPy),
and hand plain values to knowpiler.core. It must never construct a
Manifest or Config directly, never touch Pydantic, and never contain
business rules. A future web interface will collect the exact same plain
values from an HTTP request body and call the exact same core functions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, List, Optional

import typer
from InquirerPy import inquirer
from prompt_toolkit.document import Document
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Console
from rich.markup import escape

from knowpiler.core import config as cfg
from knowpiler.core import manifest as mf
from knowpiler.core.doctor import print_report, run_all
from knowpiler.core.status import get_status
from knowpiler.core.utils import clean_path

app = typer.Typer(help="knowpiler -- knowledge compiler for engineers.")
console = Console()

class CleanPathValidator(Validator):
    """Validates a path after normalizing it via clean_path() first.

    InquirerPy's own PathValidator checks the raw buffer text -- so a path
    dragged from Finder/Explorer (backslash-escaped) or copied via "Copy
    as Pathname" (quote-wrapped) gets rejected and reprompted forever,
    since the literal escaped/quoted string never exists on disk. This
    cleans first, then checks -- confirmed fix against both real-world
    patterns hit during Level 2.2 testing.
    """

    def __init__(self, is_file: bool = False, is_dir: bool = False, message: str = "Path does not exist") -> None:
        self._is_file = is_file
        self._is_dir = is_dir
        self._message = message

    def validate(self, document: Document) -> None:
        raw = document.text
        if not raw:
            raise ValidationError(message=self._message, cursor_position=len(raw))
        candidate = Path(clean_path(raw)).expanduser()

        if self._is_dir and not candidate.is_dir():
            raise ValidationError(message=self._message, cursor_position=len(raw))
        if self._is_file and not candidate.is_file():
            raise ValidationError(message=self._message, cursor_position=len(raw))


DIR_VALIDATOR = CleanPathValidator(is_dir=True, message="Path does not exist or is not a directory")
FILE_VALIDATOR = CleanPathValidator(is_file=True, message="Path does not exist or is not a file")

@app.callback()
def main_callback() -> None:
    """knowpiler - Knowledge compilation engine"""
    cfg.hydrate_env()

@app.command()
def doctor() -> None:
    """Check environment: markitdown, pygount, graphify, git, architecture."""
    console.print("[bold]knowpiler doctor[/bold]")
    ok = print_report(run_all())
    if not ok:
        console.print("\n[red]Fix the above, then re-run `knowpiler doctor`.[/red]")
        raise typer.Exit(code=1)
    console.print("\n[green]All dependencies present.[/green]")


config_app = typer.Typer(help="View or set persisted defaults.")
app.add_typer(config_app, name="config")


@config_app.command("set-backend")
def config_set_backend(
    backend: str = typer.Argument(..., help=f"one of {cfg.SUPPORTED_BACKENDS}"),
    force: bool = typer.Option(False, "--force", "-f", help="Force update existing credentials and model")
) -> None:
    if backend not in cfg.SUPPORTED_BACKENDS:
        console.print(f"[red]Unknown backend '{backend}'.[/red] Choose from: {cfg.SUPPORTED_BACKENDS}")
        raise typer.Exit(code=1)
    
    # Smart UX Routing for Notices
    if backend == "openai":
        console.print(
            "\n[cyan]◇ LOCAL SERVER (FREE)[/cyan] [dim]If using LM Studio/vLLM, paste your base URL (http://...) below.[/dim]\n"
            "[cyan]◆ CLOUD API (PAID)[/cyan]    [dim]If using OpenAI's cloud API, pasting a key means you will be billed.[/dim]\n"
        )
    elif backend != "ollama":
        console.print(
            f"\n[cyan]◆ BILLING NOTICE[/cyan]      [dim]Setting your backend to '{backend}' means you will be billed\n"
            "                      by the provider for API usage. This includes semantic extraction,\n"
            "                      knowledge file rewriting, and final artifact generation.[/dim]\n"
        )

    # 1. Load config early to manage state transitions
    c = cfg.load_config()
    
    # 2. STATE PURGE: If switching backends, wipe out any old model configurations
    if c.backend != backend:
        c.model = None
        
    c.backend = backend
    
    # The interceptor: triggers if missing, OR if the user explicitly passes --force
    if (not cfg.backend_ready(backend) or force) and backend != "ollama":
        env_var = cfg.ENV_VAR_BY_BACKEND[backend]
        
        prompt_msg = f"Enter your {backend} API key (input is hidden):"
        if backend == "openai":
            prompt_msg = f"Enter your {backend} API key OR Local Base URL (input is hidden):"
            
        user_input = inquirer.secret(message=prompt_msg).execute()
        
        if user_input:
            # SMART ROUTING: Did they paste a URL?
            if backend == "openai" and user_input.startswith("http"):
                cfg.save_credential("OPENAI_BASE_URL", user_input.strip())
                cfg.save_credential("OPENAI_API_KEY", "sk-local-dummy-key")
                console.print("[green]Local base URL saved securely! Dummy API key auto-generated.[/green]")
                
                # Close the UX gap: Ask for the explicit local model name
                local_model = inquirer.text(
                    message="Enter the exact model name running on your server (e.g., 'llama-3-8b'):"
                ).execute()
                
                c.model = local_model.strip() if local_model else "local-model"
                cfg.save_config(c)
                console.print(f"\n[green]Backend successfully set to {backend} (routing to: {c.model}).[/green]")
                return  # Exit early to prevent standard saving below
            else:
                # TRANSITION CLEANUP: If they pasted a real API key for OpenAI, we must destroy 
                # any old Base URL and model data so it doesn't hijack the cloud request.
                if backend == "openai":
                    cfg.unset_credential("OPENAI_BASE_URL")
                    c.model = None 

                cfg.save_credential(env_var, user_input.strip())
                console.print("[green]API key saved securely to ~/.knowpiler/.env[/green]\n")
        else:
            console.print("[red]Backend setup aborted.[/red]\n")
            raise typer.Exit(code=1)

    # 3. Final save for standard paths
    cfg.save_config(c)
    console.print(f"[green]Backend successfully set to {backend}.[/green]")

    
@config_app.command("show")
def config_show() -> None:
    """Display current configuration and credential status (vault + system env)."""
    c = cfg.load_config()
    console.print("\n[bold]⚙️  Current Configuration (config.toml)[/bold]")
    console.print(f"  Active Backend : [cyan]{c.backend or 'Not set'}[/cyan]")
    console.print(f"  Active Model   : [cyan]{c.model or 'Default'}[/cyan]")
    console.print(f"  Active Project : [cyan]{c.active_project or 'Not set'}[/cyan]")

    console.print("\n[bold]🔒 Credential Status[/bold]")

    status = cfg.get_credential_status()
    for backend, info in status.items():
        source = info["source"]
        if source == "vault":
            color, label = "green", "✓ Ready (vault)"
        elif source == "system":
            color, label = "blue", "✓ Ready (system)"
        else:
            color, label = "dim", "✗ Missing"
        # Pad the plain label first, then wrap in markup -- padding a
        # string that already contains [color]...[/color] tags misaligns
        # columns, since the tag characters count toward the padded width
        # even though Rich strips them at render time.
        console.print(f"  [{color}]{label:<18}[/{color}] : {backend} ({info['env_var']})")

    # Special check for the OpenAI local-server base URL interceptor --
    # same vault-vs-system distinction applies here too, not hardcoded.
    local = cfg.get_local_base_url_status()
    if local:
        url, source = local
        console.print(f"  [green]{'✓ Ready (' + source + ')':<18}[/green] : openai local URL -> [cyan]{url}[/cyan]")

    console.print()


# ---------------------------------------------------------------------------
# Collection commands (C4, C8, C11). Interfaces resolve "active project";
# core always receives an explicit manifest. Core returns Result/Problem and
# this layer is the only place that prints or exits.
# ---------------------------------------------------------------------------
ProjectOption = Annotated[
    Optional[str],
    typer.Option("--project", "-p", help="Project to act on (default: the active project)."),
]

FIX_HINTS = {
    "save_as_other": "add --save-as-other to keep it under role 'other'",
    "remove_with_evidence": "add --with-evidence to remove it together with that evidence",
}


def _load(project: Optional[str]) -> mf.Manifest:
    c = cfg.load_config()
    name = project or c.active_project
    if not name:
        console.print("[red]No project selected.[/red] Run `knowpiler init <name>` or pass -p <name>.")
        raise typer.Exit(code=1)
    try:
        return mf.load_manifest(name, c.storage_root)
    except mf.ManifestError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(code=1)


def _describe(entry) -> str:
    if hasattr(entry, "label"):  # InputEntry
        return f"{entry.id} {entry.label} ({entry.path})"
    return f"{entry.id} {Path(entry.path).name} [{entry.role}]"  # EvidenceEntry


def _print_problems(res: mf.Result) -> None:
    for p in res.problems:
        console.print(f"[red]✗[/red] {escape(p.message)}")
        if "replace_existing" in p.suggested_fixes and p.conflicting_id:
            console.print(f"[dim]  → to swap it in, add: --replace {p.conflicting_id}[/dim]")
    for fix in res.suggested_fixes:
        if fix in FIX_HINTS:
            console.print(f"[dim]  → {FIX_HINTS[fix]}[/dim]")


def _finish(manifest: mf.Manifest, res: mf.Result) -> None:
    if not res.ok:
        _print_problems(res)
        raise typer.Exit(code=1)
    if res.status != "already_collected":
        manifest.save()
    console.print(f"[green]✓[/green] {res.status.replace('_', ' ')}: {escape(_describe(res.entry))}")


@app.command()
def init(
    name: str = typer.Argument(..., help="Project name, e.g. 'Semantic Web - guide allocation'"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing project's manifest without asking."),
) -> None:
    """Create an empty project and make it the active one."""
    c = cfg.load_config()
    path = mf.manifest_path_for(name, c.storage_root)
    if path.exists() and not force:
        if not typer.confirm(f"A project already exists at {path.parent}. Overwrite its manifest?", default=False):
            raise typer.Exit(code=1)
    mf.init_manifest(name, c.storage_root, save=True)
    c.active_project = name
    cfg.save_config(c)
    console.print(f"[green]✓[/green] Project created and set active: {escape(name)}")
    console.print("[dim]Next: knowpiler add input <folder>   (then: knowpiler status)[/dim]")


add_app = typer.Typer(help="Add an input folder or an evidence file to a project.")
app.add_typer(add_app, name="add")


@add_app.command("input")
def add_input_cmd(
    path: str = typer.Argument(..., help="A folder to analyze (usually one codebase)."),
    kind: str = typer.Option("code", "--kind", help=f"Suggested: {', '.join(mf.SUGGESTED_KINDS)}"),
    label: Optional[str] = typer.Option(None, "--label", help="Your own name for it, e.g. backend."),
    replace: Optional[str] = typer.Option(None, "--replace", help="Id of an existing input this folder replaces."),
    project: ProjectOption = None,
) -> None:
    """Add a folder as an input."""
    manifest = _load(project)
    _finish(manifest, mf.add_input(manifest, path, kind=kind, label=label, replace_id=replace))


@add_app.command("evidence")
def add_evidence_cmd(
    path: str = typer.Argument(..., help="A file that supports or explains the work."),
    role: str = typer.Option(..., "--role", "-r", help=f"One of: {', '.join(mf.ROLES)} (or your own label)."),
    subtype: Optional[str] = typer.Option(None, "--subtype", help="e.g. architecture_report"),
    scope: Optional[List[str]] = typer.Option(
        None, "--scope", "-s", help="Input id this applies to (repeatable). Default: inferred from where the file lives."
    ),
    save_as_other: bool = typer.Option(
        False, "--save-as-other", help="If the file type doesn't fit the role, keep it under role 'other'."
    ),
    project: ProjectOption = None,
) -> None:
    """Add a file as evidence."""
    manifest = _load(project)
    res = mf.add_evidence(manifest, path, role=role, scope=scope or None, subtype=subtype)
    if not res.ok and save_as_other and any(p.code == "wrong_type" for p in res.problems):
        res = mf.add_evidence(manifest, path, role="other", scope=scope or None, subtype=subtype)
    _finish(manifest, res)


@app.command()
def remove(
    entry_id: str = typer.Argument(..., help="An input or evidence id, e.g. in-1 or ev-2."),
    with_evidence: bool = typer.Option(False, "--with-evidence", help="Also remove evidence scoped only to this input."),
    project: ProjectOption = None,
) -> None:
    """Remove an input or an evidence entry."""
    manifest = _load(project)
    _finish(manifest, mf.remove_entry(manifest, entry_id, cascade=with_evidence))


@app.command()
def status(project: ProjectOption = None) -> None:
    """Show what is collected, what is missing, and whether normalize can run."""
    manifest = _load(project)
    report = get_status(manifest)
    console.print(
        f"\n[bold]{escape(manifest.project)}[/bold]  ·  {report.n_inputs} input(s)  ·  {report.n_evidence} evidence file(s)"
    )
    for i in manifest.inputs:
        console.print(f"  {i.id}  [cyan]{escape(i.label)}[/cyan] ({escape(i.kind)})  [dim]{escape(i.path)}[/dim]")
    for e in manifest.evidence:
        scope = ", ".join(e.scope) or "whole project"
        console.print(f"  {e.id}  {escape(Path(e.path).name)} [dim]· {escape(e.role)} · scope: {scope}[/dim]")
    if report.findings:
        console.print()
    for f in report.findings:
        mark, color = ("!", "yellow") if f.level == "warn" else ("i", "dim")
        console.print(f"  [{color}]{mark}[/{color}] {escape(f.message)}")
    if report.ready_for_normalize:
        console.print("\n[green]Ready for normalize.[/green]")
    else:
        console.print("\n[yellow]Not ready for normalize yet.[/yellow]")
    if not manifest.inputs:
            console.print("[dim]Next: knowpiler add input <folder>[/dim]")


@app.command()
def normalize(project: str) -> None:
    """Step 2-3 -- markitdown (library), native tree, cloc/git, graphify subprocess."""
    console.print(
        "[yellow]Not yet built.[/yellow] Next: wire core.convert + core.ignore + "
        "core.treewalk together against a real manifest, plus cloc/git subprocess calls."
    )


@app.command()
def rewrite(project: str) -> None:
    """Step 4 -- semantic rewrite into Layer-2 voice, using Master_PKB as style reference."""
    console.print(
        "[yellow]Not yet built.[/yellow] Needs a confirmed backend "
        "(`knowpiler config set-backend <name>`) and real staged output from `normalize` first."
    )


@app.command()
def assemble(project: str) -> None:
    """Step 5 -- assemble the final Project Knowledge File."""
    console.print("[yellow]Not yet built.[/yellow]")


@app.command()
def review(project: str) -> None:
    """Step 6 -- human review gate."""
    console.print("[yellow]Not yet built.[/yellow]")


@app.command()
def store(project: str) -> None:
    """Step 7 -- store as Layer 2, merge into the unified Layer 1+2 knowledge corpus."""
    console.print("[yellow]Not yet built.[/yellow]")


@app.command()
def run(project: str) -> None:
    """One-shot pipeline: init -> normalize -> rewrite -> assemble -> review -> store."""
    console.print(
        "[yellow]Not yet built.[/yellow] Will chain the commands above once each is real."
    )


if __name__ == "__main__":
    app()