# knowpile — memory_guide.md

`checkpoint_0.md` is frozen at Level-0 (normalize.sh abandoned, Python
rebuild about to start) and is never edited again. Everything after that
point — all of Level-2 development — is logged here, append-only:
chronological, Level-2 semantic fidelity (rationale + fixes preserved,
prose trimmed), one entry per session.

---

## Log 1 — Core/Interface split + tool integration

- Restructured `knowpile/` into `core/` (zero UI code — no `typer`,
  `questionary`/`InquirerPy` imports) and `cli/` (prompting + display only,
  calls `core` functions, never constructs `Manifest`/`Config` directly).
- Adopted: `pathspec` for `.graphifyignore` (real gitignore semantics,
  replaces `fnmatch`); `litellm` as the unified LLM gateway (replaces
  per-backend curl/jq, built-in retry/backoff); `markitdown[pdf,docx,pptx]`
  via native Python import + `.convert_local()` only — never `[all]`
  (pulls ffmpeg/pydub/SpeechRecognition, the documented Rosetta/ARM64 crash
  cause from Level 0) and never `.convert()` (accepts remote URIs, SSRF
  surface).
- 3 bugs found via real execution, not inspection:
  1. `config.save_config()` crashed on first run — TOML has no `null` type;
     `Optional[str] = None` fields couldn't serialize. Fix:
     `model_dump(exclude_none=True)`.
  2. `ArchDiagramInfo`/`ReadmeInfo` could hold `status="collected"` while
     `path` was actually `None` (e.g. path was the literal string
     `"null"`). Fix: `model_validator(mode="after")` derives `status` from
     the cleaned `path`, never trusts it as a separately-passed value.
  3. Shell-quoted paths (`"'/Users/x/file (1,2).pdf'"`) landed in the
     manifest with literal quote characters baked into the string. Fix:
     `strip_shell_quotes()` via Pydantic `field_validator` on every path
     field.

## Log 2 — Install, verified working sequence (uv)

```bash
uv --version                    # uv 0.11.19
uv venv .kp_venv
source .kp_venv/bin/activate
uv pip install -e .
```

Resolved 91 packages (litellm, markitdown, pydantic, typer, InquirerPy,
rich, pathspec, tomli/tomli-w among them). `uv` and `pip` both read the
same `pyproject.toml` blueprint — either works; `uv` is faster and can
lock via `uv.lock`.

## Log 3 — `ModuleNotFoundError: No module named 'knowpile'` after successful install

- Symptom: `uv pip install -e .` reported success (`knowpile==0.1.0` in
  the resolved list), but every `knowpile` command failed with
  `ModuleNotFoundError: No module named 'knowpile'`.
- Root cause: not a code bug. Files were delivered individually
  (not as a structure-preserving archive), so `commands.py`, `manifest.py`,
  `config.py`, etc. landed flat in the repo root instead of inside
  `knowpile/core/` and `knowpile/cli/`. No `knowpile/` package folder
  existed at all. An editable install (`-e .`) only adds the project root
  to `sys.path` — it doesn't validate the package exists until something
  actually tries to `import` it, which is exactly where this surfaced.
- Fix: restore the nested `knowpile/core/`, `knowpile/cli/` structure,
  then reinstall.
- **One-liner:** _editable installs don't verify your package layout —
  they only trust it; deliver and extract nested-folder projects as a
  single structure-preserving archive, never as loose individual files._

## Log 4 — `questionary` → `InquirerPy` (full migration, not a hybrid)

- `InquirerPy.filepath(only_directories=True, validate=PathValidator(is_dir=True))`
  is a built-in match for the original bash `_pick_directory` loop;
  `questionary.path()` has no directory-only flag, requiring a manual
  validator to match the same behavior.
- Running both libraries side by side for one feature was rejected as
  worse than picking one — `InquirerPy` covers `confirm`/`select`/`text`
  equally well, so this is a full swap, not a two-library hybrid.
- Also added `PathValidator(is_file=True)` on every file-selection prompt
  (README/report/research/presentation/notes/arch-diagram) — existence
  checking those previously had none.

## Log 5 — `pyproject.toml` referenced a `README.md` this delivery deliberately omits

- Found while testing the fix for Log 3, not by inspection: packaging the
  corrected zip _without_ `README.md` (intentional — that file is yours,
  never to be overwritten) broke `pip install -e .` outright:
  `OSError: Readme file does not exist: README.md`, because
  `pyproject.toml` still declared `readme = "README.md"`.
- Fix: removed the `readme` key from `[project]`. It's PyPI-display
  metadata only — irrelevant to a local editable install, and the wrong
  place to reference a file this project doesn't own.
- **One-liner:** _a build config that references a file by name creates a
  hard dependency on that file existing — don't declare it if you don't
  intend to ship it._

## Log 6 — src/ layout migration + .gitignore hardening

- Moved `knowpile/` -> `src/knowpile/`. Reason: flat layout (package folder
  at repo root) lets Python accidentally import the local source folder
  instead of the installed package if a script is ever run directly from
  repo root -- `src/` isn't auto-importable, so it structurally prevents
  that class of bug rather than just avoiding it by habit. Considered and
  rejected staying flat (graphify itself uses flat layout successfully) --
  decided the src/ move was still worth it given this project already hit
  two packaging/import-path bugs (Log 3, Log 5) in one session.
- Only change required: `packages = ["knowpile"]` -> `packages =
["src/knowpile"]` in `[tool.hatch.build.targets.wheel]`. No code changes
  -- internal imports were already absolute (`from knowpile.core import
...`), never relative to repo root.
- Verified: `uv pip install -e .` (92 packages) + `knowpile doctor` — all
  5 checks OK on the real machine, including graphify and cloc now
  correctly detected.
- `.gitignore` was covering project content (Artifacts/, Layer_0/,
  Layer_1/) but nothing Python-specific -- `.kp_venv/` and every
  `__pycache__/` were trackable. Added `.kp_venv/`, `__pycache__/`,
  `*.pyc`, `*.egg-info/`, `.env`. `memory_guide.md` also added to
  `.gitignore` -- project is in ideation phase, `README.md` (currently at
  checkpoint-0/Level-0 state) is the public-facing file, the build log
  stays private for now.
- rebrand: knowpile -> knowpiler : Root folder, GitHub repo, package import path, CLI command all renamed.
- Fixed by clean regeneration rather than further patching, verified via
  fresh install + `knowpiler doctor` (5/5 checks, correct ~/.knowpiler/ path).

## Log 7 — Plug & Play Architecture: Venv Isolation & Secure Credential Vault

- **Dependency Isolation**: Locked `graphifyy`, `pygount`, `python-dotenv`
  into `pyproject.toml` — no reliance on global system binaries.
- **Doctor (`doctor.py`)**: `graphify` check scoped to the venv's own
  executable dir via `shutil.which(path=venv_bin_dir)` — cross-platform by
  construction. Dropped `cloc`; `git` softened `FAIL`→`WARN` (optional,
  not blocking).
- **Secure Vault (`config.py`)**: `~/.knowpiler/.env` holds keys, injected
  into `os.environ`. `chmod 600` guarded to POSIX only (`os.name != "nt"`).
  Hydration moved from an import-time side effect to an explicit
  `hydrate_env()`, called once via Typer `@app.callback()`. Added
  `unset_credential()`, symmetric with `save_credential()`.
- **Smart UX (`commands.py`)**: Masked `InquirerPy` prompts. Local-model
  routing — an `openai` URL paste sets `OPENAI_BASE_URL` + dummy key, then
  prompts for the real local model name (so `litellm` doesn't default to a
  cloud model string against a local server). Billing notice reordered:
  `openai` shows free-local vs. paid-cloud _before_ input, not a blanket
  warning.
- **Base URL Poisoning fix**: `--force` re-triggers the prompt for an
  already-configured backend. Pasting a real `sk-...` key purges any stale
  `OPENAI_BASE_URL` and resets `model` — otherwise it would silently
  hijack a real, billed call. `model` also resets on any backend switch
  (not on same-backend re-confirm).
- **`config show`**: rebuilt from a raw dict dump into a vault-status view
  — per-backend credential presence only, never secret values.

Verified via live `set-backend`/`config show` runs, including a
before/after-`--force` cycle and a clean-terminal re-run of a plain
switch.

## Log 8 — Level 2.2 Planning: `normalize` Architecture Lock-In (Ideation, No Code Yet)

Entire session was pure architecture/UX ideation for the `normalize`
command (Level 2.2) — **zero code written**. Purpose: resolve every open
design question before touching `core/normalize.py`, deliberately
front-loaded to avoid "multiple LLMs hallucinating different pipeline
architectures" spaghetti (explicit concern raised mid-session after a
noisy multi-model detour). Follows the project's own stated SDLC instinct
— build → use → update → finalize, one small piece at a time — rather than
blind waterfall.

**Static analysis of Log-7 baseline confirmed handoff.md's four original
open questions**, with one gap not previously logged:

1. Reuse `core.convert.convert_file()` for Phase 2 (shared `MarkItDown()`
   instance across calls, isolates failures via `ConversionResult`) —
   confirmed correct; only new work is dispatch/orchestration logic.
2. `normalize(project)` must load the `Manifest` and drive phases off
   recorded fields, never re-discover directories — confirmed
   non-negotiable. Found the actual `load_manifest()` helper doesn't
   exist yet; `staging_dir` derivation currently only lives inline inside
   `create_manifest`.
3. Partial-failure tolerance already modeled by `ConversionResult.ok/error`
   — orchestrator must propagate this as an aggregate result, not raise
   or silently swallow. Confirmed correct.
4. LLM-assisted `.graphifyignore` suggestion — demoted to optional/
   additive, not automatic-every-run (fully resolved later in session,
   see below).
5. **New gap, found by inspection:** `treewalk.render_tree()` and
   `ignore.filtered_files()` are two disconnected utilities — treewalk
   only returns a display string; filtered*files is the only actual
   usable `List[Path]` data source. handoff.md's Phase-1 description
   implied these were already joined; they are not. Also: `ignore.py` has
   no \_write* path — `graphify` reads `.graphifyignore` from disk as an
   independent subprocess, but nothing materializes in-memory
   fallback/derived patterns onto disk.

**A local-model-authored "Phase 1+2" code drop was reviewed line-by-line
and mostly rejected, not accepted wholesale:**

- Its `ignore.py` rewrite (`get_ignorer`/`is_ignored`) silently changed
  precedence — original: "if `.graphifyignore` exists use ONLY that, else
  fall back to `.gitignore`+static net"; rewrite: always layers all three
  unconditionally. Rejected as an undocumented behavior change. One good
  idea kept for later: excluding `.knowpiler/` from scans.
- Its `treewalk.py` fix (single-pass tree-string + file-list) was the one
  genuinely correct diagnosis — shape kept, but must call the _existing_
  `ignore.py` functions, not the rewritten pair.
- Its `parser.py` used `md.convert()` instead of `convert_local()` — a
  real SSRF-surface regression against a deliberate Log-1 decision.
  Non-negotiable rejection.
- Its flat `DOC_EXTENSIONS` extension-sniffing doesn't match the
  manifest's evidence model (notes are md/txt-native and should be
  copied, not converted; nothing in the schema produces json/html/xml/csv
  evidence). Dispatch must be by manifest category, not raw extension.
- Its CLI wiring took a raw filesystem path arg (undoes point 2 above)
  and gated the _entire_ `normalize` command on `c.backend` being set —
  too broad; only the optional ignore-suggestion sub-step needs a
  backend.
- Its output path (`cfg.KNOWPILER_HOME/"workspace"`, fixed filenames) is
  project-agnostic — a second project's run would overwrite the first's.
- Its error handling (`except Exception: pass`, unstructured error
  strings) is weaker than the already-validated `ConversionResult`
  pattern.

**User's own reconciled "Architectural Rulings" locked in:**
`load_manifest(project)` as the only entry point (no raw-path arg);
confirm-gated overwrite on rerun (not silent always-overwrite, not
`run{i}` versioning — reuses the existing `inquirer.confirm` pattern from
`init`); `.graphifyignore` write-path required before Phase 3; fault
tolerance propagated through the orchestrator via `ConversionResult`-style
results. **Build order locked:** Step A (patch `manifest.py`+`ignore.py`
with small standalone-testable functions) → Step B (`core/normalize.py`
orchestrator, testable without Typer) → Step C (CLI wiring, last).

**Manifest format stays JSON** — already tested serialization since
Log 1–3; no reason to introduce TOML for a generated, non-hand-edited
artifact.

**`init` confirmed not broken** — the reported error was a Typer usage
gap (`project` is a required positional `typer.Argument`), not a
regression.

**Real bug found via live execution, misdiagnosed once then corrected:**
dragging/pasting a path from Finder into the terminal produces a path
wrapped in matching quote characters (first suspected as backslash-
escaping — explicitly wrong, corrected once the user re-tested and pasted
the actual failing string). Root cause: `utils.strip_shell_quotes()`
already exists and already handles this, but only runs inside `Manifest`'s
Pydantic validators — which fire _after_ `commands.py`'s
`PathValidator(is_file=True)` already rejected the raw string and forced
an infinite reprompt loop (the repeated-identical-prompt log, plus a
"window too small" `prompt_toolkit` redraw artifact, were symptoms of this
one loop, not separate bugs). **Fix agreed (not yet written):** a shared
`clean_path()` in `utils.py`, extending — not duplicating —
`strip_shell_quotes()` to also handle backslash-escaped characters, called
at the CLI validator layer _and_ still used in the Pydantic layer. Bumped
to the very first build step, ahead of Step A, since every later phase
assumes the manifest holds real, uncorrupted paths.

**`storage_root` default reconsidered on findability grounds, not
customizability grounds.** A proposal for per-project custom staging
locations (OS-specific Documents/Downloads defaults) was rejected as scope
creep — single existing default kept. Separately, a narrower objection
surfaced: `~/.knowpiler/` is a dotfolder, hidden by default in
Finder/Explorer — a real problem given the project's copy-paste-a-path,
no-GUI workflow. Resolved: keep `~/.knowpiler/` (hidden) for
credential-adjacent files only (`config.toml`, `.env`); move project data
to a new visible root, `~/knowpiler-projects/<project-slug>/staging/` —
one default-value change in `config.py`, project-first folder grouping
(one project = one browsable folder; extensible later for an `artifacts/`
sibling without restructuring).

**`.graphifyignore` location resolved empirically**, not guessed, from the
user's own two independent real-project debugging sessions: in both, the
ignore file was created/populated at the project **root**
(`data/`, `models/`, `py3.10-venv/` as root-relative patterns), and
`graphify extract src/` — invoked against the _subdirectory_ — still
respected those root-anchored patterns (observed both times: "stuck on 8
files" → "semantic extraction on 1 file" after populating). **Locked:**
`write_graphifyignore()` always targets `code.root_dir`, regardless of
whether graphify is later invoked against `root_dir` or a `src_dir`.

**LLM-tailored `.graphifyignore` generation confirmed as the right
approach.** `ignore.py`'s own Log-1 docstring already anticipated this
("must never depend on a network call succeeding just to filter files")
— completing an already-half-built plan, not new architecture. Locked
shape: additive on top of the existing static safety net, never a
replacement; input is the tree structure already produced by
`treewalk.render_tree()` (no new data-gathering); LLM output sanitized
(strip comments/blanks, reject anything that could wipe the whole ignore
surface) before `write_graphifyignore()` touches disk; which path was
used (LLM vs. static-fallback) logged on the Manifest, mirroring the
existing `backend_used`/`model_used` traceability pattern. This is the
only sub-step of `normalize` gated on a configured backend; absence
degrades gracefully to static+`.gitignore` fallback, never blocks the
command.

**Multi-source-root gap identified from the user's own real project
inventory** (an LMS project with separate `ShoonyaVeer-LMS-main` frontend
and `Shoonyaveer-lms-backend-main` backend folders at one root; a Laravel
project with `app/` vs `routes/` split) — a single `src_dir: str` cannot
represent either case. Researched real-world precedent (JetBrains'
monorepo guidance: separate indexing per root, not one blended scan)
before locking: **`CodePaths.src_dir` becomes `src_dirs: List[str]`** in
`manifest.py` — a genuine schema change, flagged explicitly rather than
folded silently into UX work. Consequence for Phase 3: `graphify` invoked
once **per** `src_dir`, each producing its own `graphify-out/` and its own
`.graphifyignore` at that root — deliberately not one merged graph, since
frontend/backend (or `app/`/`routes/`) are architecturally distinct. A
one-line UI footnote agreed: state once, at the codebase-collection step,
that different roots are scanned/graphed independently for a clearer
per-codebase graph — not repeated at every prompt.

**Evidence-collection UX redesigned as two-tier batch-review**, adopted
from the user's own proposal essentially as-is: collect a full category
(e.g. all reports) → show that batch back with filenames stripped of
noisy full paths → edit/remove/pass on that batch → next category → after
all categories, one final full recap across everything → last
edit/remove/pass → save. Rejected in favor of this: per-item mid-loop
editing (jumping back to retag entry #2 while entry #4 is mid-prompt) —
too much state-juggling for the gain. Applies uniformly to every list-type
manifest field (reports, research, presentations, notes, `src_dirs`).

**Manifest schema also needs to persist pipeline outcomes, not just
evidence paths** — user's own catch, bundled into the same `manifest.py`
change as the `src_dirs` migration: a conversion-log field (per evidence
file: path, ok/error, timestamp — promoting `core.convert.ConversionResult`
from transient dataclass to persisted state) and a graphify-run-log field
(per `src_dir`: root, output path, pass/fail, timestamp). Not populated
until `normalize`/Phase 3 actually run; schema agreed now since it's the
same file being edited anyway.

**`init` defaults corrected against real evidence:** `src_dir` default
guess (`{root_dir}/src`) is wrong for most non-JS-frontend projects —
neither the Laravel tree nor the LMS backend tree has a `src/` folder at
all. Changed to default-suggest `root_dir` itself, not a hardcoded `/src`
guess. README auto-detection (checking common filename variants at
`root_dir` before prompting) added as new logic.

**GUI/browse-mode debate, resolved in two rounds.** Round one: "GUI-like
file explorer" request initially misread as OS-native file dialogs
(Finder/Explorer pickers), pushed back on as unnecessary platform-specific
complexity; corrected once user clarified via a VS Code sidebar
screenshot — the actual ask was a terminal-rendered expandable tree, not
an OS dialog. Round two: user surfaced two competing external proposals
(PySide6/Qt native picker vs. Textual-based TUI picker) for evaluation.

- **PySide6/Qt rejected firmly**, not as a style call — contradicts
  `commands.py`'s own stated architecture (a Qt window is neither a
  terminal collector nor compatible with the "same plain values, future
  web interface" model), breaks SSH usage, reverses the Level-0
  bash→Python pivot's own cross-platform/terminal-native rationale.
- **Textual confirmed via live research as strictly better than the
  earlier-proposed `pickpack`:** `pickpack` is curses-based, needing
  `windows-curses` on Windows (a real gap already flagged once); Textual
  is built on Rich (already a dependency) with its own terminal driver —
  no curses dependency, confirmed cross-platform natively — and ships a
  `DirectoryTree` widget out of the box with a built-in `filter_paths()`
  hook, meaningfully less custom code than assembling `anytree`+`pickpack`.
- **Feature list from both proposals triaged individually**, not accepted
  or rejected wholesale, given the user's explicit wish to make this
  specific component genuinely polished (it's reused on every `init` run):
  - **Keep:** expandable tree view (free via `DirectoryTree`); fuzzy/live
    search (justified directly by the Laravel tree's deep nesting seen
    this session; `rapidfuzz` to be declared as an explicit dependency
    rather than relied on transitively via `graphifyy`); multi-select on
    list-type fields only (reframed as directly reducing the cost of the
    newly-agreed batch-collection loops — launch picker once per category,
    not once per item); auto-derived "favorites" sourced from existing
    projects' manifests already under `storage_root` (zero new
    state/management UI, unlike true bookmark CRUD).
  - **Cut:** preview panel (duplicates work `markitdown` does moments
    later in `normalize`; full PDF/image preview needs extra
    rendering-protocol dependencies for marginal benefit — optionally
    shrinkable to text/md-only first-few-lines, otherwise cut entirely);
    hidden-file toggle (dotfiles already excluded by `ignore.py`'s
    existing static safety net); Nerd-Font-glyph icon detection with
    install/fallback logic (**technically impossible as specified** —
    Nerd Fonts are a terminal-emulator-level font resource, not something
    a venv/`pip install` can provision; replaced with a plain-Unicode-
    emoji extension→icon map, preserving the actual goal — a distinct
    icon per filetype — without the impossible "install a font into the
    user's terminal" step). A `Ctrl+H` keybinding conflict in the user's
    own trimmed list (double-bound to a cut hidden-file-toggle and to
    multi-select) resolved itself once hidden-file-toggle was cut —
    multi-select reverts to `Space`, matching the original external
    proposal.

**Full locked build order at end of session (nothing left open):**

1. `clean_path()` in `utils.py` — extends `strip_shell_quotes()`, wired
   into both the CLI validator layer and the existing Pydantic layer.
2. `manifest.py`: `CodePaths.src_dir` → `src_dirs: List[str]`; add
   conversion-log and graphify-run-log fields.
3. `config.py`: `storage_root` default → visible `~/knowpiler-projects/`,
   keep `~/.knowpiler/` for `config.toml`/`.env` only.
4. `init` flow redesign: multi-root collection loop, two-tier
   batch-then-review UX, corrected `src_dir`/README defaults, multi-root
   footnote.
5. Textual-based browse mode: `DirectoryTree` + fuzzy/live-filter +
   multi-select (list fields) + auto-derived favorites + plain-emoji icon
   map + optional text/md-only preview; new explicit deps (`textual`,
   `rapidfuzz`); one `doctor.py` importability check matching the
   existing `markitdown`/`pygount` pattern.
6. `normalize` Step A (patch `manifest.py`+`ignore.py`: `load_manifest()`,
   `write_graphifyignore()` anchored at `root_dir`) → Step B
   (`core/normalize.py` orchestrator, manifest-category dispatch,
   per-`src_dir` graphify invocation, `ConversionResult`-style aggregate
   fault tolerance) → Step C (CLI wiring in `commands.py`, last).

**Status at end of session:** zero code written — pure architecture/UX
lock-in for Level 2.2. Every open question from handoff.md Section 7,
plus several new ones surfaced only by real dogfooding (`init` run
against actual projects: ASL sign-language project, LMS project, two
Laravel/Hotel-Management-style projects), now resolved with explicit
rationale recorded above. **Next actual coding step:** item 1 above
(`clean_path()`), standalone and testable, before anything else moves.

---

## Log 8 — ERRATA (added 2026-10-29; Log 8 text above is left intact, append-only)

- **Staging path:** Log 8 says `~/knowpiler-projects/<slug>/staging/`. Code (verified)
  sets `staging_dir = storage_root/<slug>` — `manifest.json` sits directly in the
  project folder, no `staging/` child. Proposed for `normalize`: write to
  `<slug>/normalized/`. Not yet decided.
- **"Next step: item 1" is superseded.** Items 1–4 are done (Log 9). Item 5 (Textual
  picker) was NEVER delivered: it was written in a scratch sandbox, never
  compile-checked, and lost. Picker is now deferred until after `normalize`/`rewrite`.
- **Log 1 claim "pathspec replaced fnmatch" is only half true:** `treewalk.py` still
  uses `fnmatch` + its own `DEFAULT_IGNORES`.
- **`.graphifyignore` at `root_dir`** (derived from two real tests) still stands, but
  was never re-tested on pathspec 1.x (see Log 10).
- Title fixed from "knowpile" to "knowpiler". Logs 1–6 keep the old name (history).

## Log 9 — Implementation of Log 8 items 1–4 (sessions 2026-07-21/22, verified by live runs)

- **`clean_path()` (`utils.py`)** replaces `strip_shell_quotes`. Handles quote-wrapped
  and backslash-escaped paths; Windows `C:\` / UNC paths are never un-escaped. Used at
  two layers: `CleanPathValidator` in `commands.py` (clean THEN check — the old
  `PathValidator` rejected the raw string, causing an endless reprompt loop) and the
  Pydantic validators in `manifest.py`. Later also `filter=clean_path` on all 9
  `inquirer.filepath` calls, because validation alone left quotes in the returned value
  (trailing `'` showed in review screens; manifest was still clean).
  First diagnosis (backslashes) was wrong; real failing input was quote-wrapped.
- **`manifest.py`:** `CodePaths.src_dirs: List[str]` (was `src_dir`); `CodePaths` now
  cleans paths (it was the only model that didn't); new `ConversionLogEntry`,
  `GraphifyRunLogEntry`; `conversion_log`/`graphify_log` on `Manifest` (empty until
  `normalize` runs). `SCHEMA_VERSION` was NOT bumped (still 1) — defect, see Log 10.
- **`config.py`:** `KNOWPILER_PROJECTS_HOME` (`~/knowpiler-projects`, env-overridable)
  is the visible home for project data; `knowledge_root` = `.../_knowledge`.
  `~/.knowpiler/` (hidden) now holds only `config.toml` + `.env`. Gotcha hit live:
  `save_config` writes default-derived paths, so an old `config.toml` froze the old
  hidden path; fixed by hand-deleting it.
- **Credential status:** `get_credential_status()` / `get_local_base_url_status()` merge
  vault (`~/.knowpiler/.env`) and `os.environ`; states `vault` / `system` / `missing`.
  Cause: a shell-exported `GEMINI_API_KEY` showed "Missing". `config show` rebuilt
  (padding computed before markup); dead duplicate `config_show` removed; `os` access
  stays in `core`.
- **`init` redesign:** `_collect_more` + `_review_batch` shared helpers; multi-root
  source loop with a one-line footnote; default source root = `root_dir` (not `/src`);
  per-category review (remove one / start over); final recap with redo of any list
  section. README and arch diagram are shown but not redoable.
- **Verified live (MacBookAir):** multi-root LMS project, quoted + escaped paths,
  remove/start-over/recap flows, `config show` → "Ready (system)". Pushed to GitHub;
  second machine pulled `d1208ce..90b2bb0` cleanly.
- **Not done:** README auto-detect, extension enforcement, duplicate rejection, picker,
  `normalize` (still a stub), `rewrite`+.

## Log 10 — Re-sync on new machine, audit, research reset (2026-10-29; no feature code)

**Environment:** new Mac (`N-I-T`, `~/dev/Projects/knowpiler`, Python 3.14.7, `venv/`).
`uv pip install -e .` resolved 128 packages (pathspec 1.1.1, litellm 1.104.2,
graphifyy 0.9.84, rich 15, typer 0.27); `doctor` all OK. Per-machine state is NOT in git
(`config.toml`, `.env`, `~/knowpiler-projects`) → re-ran `config set-backend gemini`.
`knowpiler init` with no argument fails (Typer required arg) — make it optional + prompt.

**Verified defects (queue for the hygiene batch):**

1. `ignore.py` uses `"gitwildmatch"`: DeprecationWarning on every pattern under
   pathspec 1.x. Fix = `"gitignore"` AND pin `pathspec>=1.0` (names swap status in 0.12).
2. `llm.py` default model names (`claude-3-5-sonnet-20241022`, `gemini/gemini-2.0-flash`)
   are absent from litellm 1.104.2's model table — unverified; active backend is gemini.
3. `save_config` persists defaults → use `exclude_defaults=True`.
4. `treewalk.py` duplicates ignore logic (fnmatch) → consolidate in `normalize` Step A.
5. `schema_version` still 1 after the `src_dir`→`src_dirs` break; old manifests die with
   "code.src_dirs Field required". Bump to 2 + readable "re-run init" error.
6. Extension rules not enforced: prompts say "pdf/docx only" but only existence is
   checked (a PDF was accepted as a _note_). `normalize` dispatch assumes notes are text.
7. Duplicate paths accepted (same PDF twice under two report types).
8. MarkItDown returns an EMPTY string (no error) for scanned PDFs; `ConversionResult`
   would record success → add an empty-output check (mark failed, continue; don't halt).
9. Stale text: `cloc` in 3 places in `commands.py`; README auto-detect never built.

**Research (sources checked, not trusted blindly):**

- Textual is not a "basic TUI" ceiling: Toad (by Textual's author) is a Claude-Code-style
  agent UI in Python; also runs in a browser via `toad serve`; works on Python 3.14.
- Claude Code internals quoted by the reports (line counts, "QueryEngine", permission
  tiers) come from unofficial sourcemap-extracted copies and disagree across sources.
  Do not build on them; never copy that code.
- Anthropic: workflows = predefined code paths; agents = model picks steps. Use the
  simplest thing; agents only when the path can't be hardcoded but progress is
  verifiable. Knowpiler's compile pipeline = a workflow. "Drafter/Reviewer" = workflow
  steps, not autonomous agents.
- PDF: MarkItDown ranks low on PDFs (layout, tables, scans). `pymupdf4llm` is **AGPL-3.0**
  (project is MIT, web UI planned) → NOT adopted. Docling is MIT but heavy (PyTorch);
  consider only as an optional extra, after testing on the user's own PDFs.
- Auto-apply: LinkedIn and Indeed terms prohibit bot automation; driving a logged-in
  session is the risky pattern. Decision: **prepare, never auto-submit.** (Sources are
  vendors with a slant; treat as directional, not legal advice.)
- graphify provenance tags (EXTRACTED / INFERRED / AMBIGUOUS), Leiden communities and
  god nodes exist. Its "71.5x" is from one 52-file benchmark, not a general guarantee.
  EXTRACTED edges prove structure (imports/calls), not prose claims.

**Two external AI reports reviewed:**

- _Report A (architecture blueprint):_ good — reconciliation idea, vertical-slice advice.
  Wrong — says `load_manifest` already exists in code (it doesn't) and a `staging/`
  path; recommends AGPL `pymupdf4llm`; its Q1–Q5 are "approve option A" (the habit that
  caused the vibe-coding problem).
- _Report B (theory + paper roadmap):_ keep — dependency-manifest check of tech claims;
  empty-output check; "prepare + human gate"; 3-level claim status. DISCARD — the
  benchmark table (numbers for a system whose `normalize` isn't built = fabricated,
  and it breaks the project's own Honesty Rule), "hallucination rate 0.00 / absolute",
  the 30-repo study, the math notation, and the ICSE schedule (every date is already
  in the past as of today).

**Decisions:**

- Restart the _thinking_, not the code: engine decisions (manifest as single source of
  truth, per-root graphify, fault-tolerant conversion, `clean_path`, vault, core/UI
  split) are interface-independent and stay.
- Pipeline first (`normalize` → `rewrite` → `review`); Textual shell later.
- No multi-file code drops. Protocol: explain concept → user predicts → one function →
  user runs it → log what surprised us.
- **Evidence ladder** for every technical claim: (1) only mentioned in docs →
  (2) declared in a dependency file → (3) imported in code → (4) used in a central code
  path. Unverified claims never reach a resume without the user's explicit approval.
- Hypothesis (to be confirmed by user's answer to Q1): first product slice = one project
  → evidence-linked knowledge file + interview-defense sheet.

**Open questions for the user:** Q1 what exactly hurt in the last rejection/interview;
Q2 who the first users are (terminal vs browser); Q3 which real project is the test
subject; Q4 paper/publication goal or product/portfolio only.

**Status:** docs now match code. Next: hygiene batch (items 1–9 above) → `normalize`
slices → `rewrite` v0.

## Log 11 — Product recalibration: answers locked, scope ladder, foundation rules (2026-10-29; no code)

**Answers to Log 10's open questions (from the user):**

- Q1: no personal rejection/interview story. The problem is _observed_ (students + job seekers
  in the AI era), so "vibe-coders get rejected" is a **hypothesis**, not a README fact. Validate
  by dogfooding, then watch 3–5 friends run the first slice.
- Q2: first user = the author; then friends; then the whole dev community (open source).
- Q3: tested on the author's own projects, committed + pushed from day 1
  (`github.com/Nittaany/knowpiler`). Used in `init` tests so far: ASL sign-language project and
  the LMS multi-root project. The specific T1 test subject is still to be named.
- Q4: project goal first → paper only if it works well → product only if people like it.

**Vision (user's diagram):** fragmented artifacts (code, reports, READMEs, slides) → knowledge
engine (de-obfuscate vibe-coded logic, AST call paths, claim audit) → canonical source of truth
(CDPKB, Layers 0–3) → four projection families: _GitHub polish_ (architecture docs, flow
diagrams, clean READMEs), _social branding_ (X/LinkedIn/Dev.to drafts, "lessons learned"),
_high-signal ATS_ (tailored 1-page CV, cover letters, cold emails), _interview defense_ (god-node
walkthroughs, trade-off sheets, STAR cards). Later: job discovery/matching against the personal
knowledge graph, publishing, apply-assist.

**Three-layer model (the whole product in one sentence):** ENGINE (evidence → approved
knowledge) → PROJECTIONS (knowledge → outputs) → ADAPTERS (outside world: job sources,
publishers). Interfaces (CLI / Textual TUI / later web / maybe MCP) only call the engine.

**Foundation rules:** (1) approved knowledge is the only source of truth, outputs are views;
(2) every technical claim carries an evidence level, gaps stay `[UNKNOWN]`; (3) a human approves
before anything is stored or sent; (4) code checks what code can check (dependencies, imports,
line counts) — the LLM never decides those facts; (5) adapters are optional, isolated,
official-API-only, reads before writes, no session/browser automation, apply = prepare and
stop; (6) local-first + open source: files go only to the user's chosen LLM provider, no
secrets in git. Build by vertical slice, each slice shipped with a test.

**Outside-world research (secondary sources — re-verify against official docs per adapter):**

- Job discovery: Greenhouse / Lever / Ashby expose keyless public job-board endpoints
  (`boards-api.greenhouse.io/v1/boards/{token}/jobs`, `api.lever.co/v0/postings/{site}`,
  `api.ashbyhq.com/posting-api/job-board/{name}`). Lever says third-party scraping is allowed
  (1 request/s); Ashby is public but not explicitly licensed. Needs company slugs — no universal
  search; broader search would need an aggregator (unchecked).
- LinkedIn: posting to own profile via "Share on LinkedIn" (`w_member_social`) is open and
  self-serve; NO self-serve job-search API; tokens short-lived; ~150 posts/day/member.
  Job finding on LinkedIn therefore cannot go through the API.
- X: no free tier for new developers since 2026-02-06 (pay-per-use): ~$0.015 per plain post,
  ~$0.20 per post containing a URL (July 2026 figures; pricing changed twice in 2026).
  → X is draft-only by default, optional.
- Instagram and Dev.to: NOT yet checked.

**Scope ladder (replaces "Levels"; "Layers" stay as the knowledge-file taxonomy):**
T0 collect (done) · T1 engine: normalize → rewrite → review for ONE project · T2 offline
projections (interview-defense sheet, architecture doc + generated flow diagram, README draft,
resume bullets + 1-page CV, cover letter, post drafts — all plain files, with a drift check
that flags any fact not in approved knowledge) · T3 identity (Layer 3 timeline + multiple
projects/Layer 1) · T4 read-only job discovery + fit/gap report · T5 write adapters (LinkedIn
own-profile post via official API with approval gate; X draft-only; apply = fill and stop).
Textual shell grows alongside, starting after T1 works. Adapters share one small interface so
contributors can add job sources/publishers without touching the engine.
Old mapping: former "Level 2.2 normalize" = T1 slice.

**Open-source baseline added to the queue:** pytest + a minimal GitHub Actions check (zero
tests exist today); rewrite the checkpoint-0 README to match reality; privacy/egress notice
(what is sent to which LLM; local models via Ollama); small competitor scan before any
"unique" claim; keep `.env`, `Artifacts/`, `Layer_*`, personal evidence out of git.

**Risks recorded:** scope (real value = T1 + T2; touch nothing external before T1 works on a
real project) · LLM-step quality is the product risk (bland knowledge → bland everything) ·
platform terms/prices drift (keep adapters swappable) · privacy of reports/code sent to cloud
LLMs · competitors unmapped.

## Log 12 — Architecture review round 3: harness vision, Docling decision, Sprint 0 micro-slices (2026-11-02; no code)

**Vision addition (user):** a BYOK, Claude-Code-style experience. Decision: pipeline = fixed
workflow (engine); the "harness" = a Textual shell over the engine where a BYOK model (litellm)
can call stages as tools with approval gates; agentic chat only later (e.g. "tailor CV to this
JD"); an MCP server later = distribution inside Claude Code / Cursor / Codex. Rule: all evidence
text (READMEs, PDFs, code comments) is untrusted data, never instructions (prompt injection).

**Docling vs MarkItDown (both run locally):** MarkItDown built-ins are offline; cloud only if
the user opts into Azure Document Intelligence/Content Understanding (billable) or passes an
LLM client for image descriptions. Docling: ~1.2–1.4 GB models downloaded once on first use
(then offline), ~1.8 GB install with CPU-only PyTorch, several GB with the default CUDA stack;
speed unmeasured (one README: 8–10 min for 32 pages on CPU); Python 3.14 reportedly OK (CPU
torch wheels for 3.14 from torch 2.9); library license permissive (Apache-2.0 per one README)
but each model has its own license → check before bundling. **Decision:** MarkItDown stays the
default; Docling = optional extra `knowpiler[layout]`, offered when a PDF comes back empty/short/
garbled; `markitdown-ocr` (user's own vision LLM) is an optional scan path — it silently skips
OCR without an LLM client, so the empty-output check stays. Before changing any dependency: run
both engines on the user's own 3 PDFs (bake-off).

**Rich vs Textual:** logs never said Rich is discarded (Textual is built on Rich). Both stay.
Textual shell moved EARLIER: after Sprint 0 + event protocol, before `normalize`. `init` stays
plain CLI (InquirerPy prompts cannot run inside a Textual screen) until a Textual form/picker
exists; Shell v0 starts with the non-interactive stages (normalize, rewrite, review).
Shell v0 = header (project/backend/model), stage list, log viewport, footer keys; no picker.

**Third-party advice triaged:**

- ADOPT: Python >=3.11 (3.10 reached end of life Oct 2026; drops `tomli`); `encoding="utf-8"`
  on every read/write (ignore.py reads .gitignore with default encoding); `os.walk(topdown=True,
followlinks=False)` with in-place `dirs[:]` pruning instead of `rglob` (it entered
  node_modules before filtering); create `.env` with 0600 at creation (chmod-after-create gap);
  `keyring` + `.env` fallback (own later slice); graph adapter `extract_code_graph()` returning
  our own `CodeGraph` model; event callbacks `on_event` in core (CLI/TUI/web render them);
  retry-once Pydantic structured output (local models ignore schemas); cost meter from measured
  `response.usage`, "unknown" for unmapped models, never an invented compression ratio;
  CI matrix ubuntu/macOS/windows x Python 3.11–3.14.
- SKIP: `platformdirs` (`~/.knowpiler` already cross-platform; Claude Code/Codex/Gemini CLI also
  use dot-folders in home); JobSpy (scrapes LinkedIn/Indeed → violates official-API-only rule).
- LATER: cloning GitHub URLs (sandbox first; plain `git clone --depth`, hooks off); `textual
serve` = demo only (one process per user, not multi-tenancy).
- REJECTED: one mega-slice (pyproject + 5 new deps + config rewrite at once); hard-coded model
  tables copied from chats; adding deps (`textual`, `rapidfuzz`, `keyring`) before code uses them.
- UNVERIFIED: graphify advisory IDs SFTY-20261019-82834 / GHSA-pcc4-rvhr-2pr8 — searches found
  nothing; do not repeat them. Upgrading is still sensible (0.9.94 added URL-validation
  hardening; 0.9.95/0.9.96 exist). graphifyy shipped ~90 patch releases in ~4 months (0.9.5 on
  Jul 2 → 0.9.96) → exact pin + adapter + contract test on a golden `graph.json`.
- litellm model names: keep defaults in ONE dict, unit-test that each exists in litellm's
  registry, let the user override; never trust a list from a chat (including this one).

**Sprint 0 = micro-slices, one change + one test each, in this order:**
0a `pyproject.toml` (python>=3.11, pathspec>=1.0, exact graphifyy pin, dev extra pytest) ·
0b `config.py` (drop tomli, `exclude_defaults=True`, 0600 at creation) ·
0c `ignore.py` (utf-8, pruned walk, `"gitignore"`, `write_graphifyignore`; delete `treewalk.py`) ·
0d `manifest.py` (schema 2, `load_manifest`, extension + duplicate checks, utf-8) ·
0e `convert.py` (empty-output check, mark failed + continue) ·
0f `llm.py` (registry-verified defaults, retry-once structured output, measured cost) ·
0g pytest + GitHub Actions matrix · 0h `commands.py` (optional `init` arg, README auto-detect,
stale `cloc` text). Then: event protocol → Shell v0 → `normalize` slices (graph adapter built
inside the graphify slice).

**Defaults assumed (user had not answered; change if wrong):** `init` stays plain CLI for now;
Python >=3.11; T1 test subjects = ASL sign-language (single-root) + LMS (multi-root).
**Note:** Log 10/11 dates (2026-10-29) are left as written; this log uses today's date.

## Log 13 — Restart under a single architect; review of an external "Chunk 0.1"; slices 0a + 0b (2026-11-02)

**Final rulings (user):** (1) `~/.knowpiler` (hidden, internal) + `~/knowpiler-projects`
(visible, results), same layout on every OS, both env-overridable; no `platformdirs`. (2) Providers,
models and gateways are 100% dynamic — no hardcoded model names (BYOK cloud, local servers, LiteLLM
proxy, OpenRouter, anything litellm supports). (3) Nothing specific to the author's projects;
test fixtures are synthetic. Added vision item: "self-improving learning paths" (gap analysis →
plan) as a later projection. The user appointed one architect to own the plan end to end.

**Automation stance (restated):** official APIs inside documented limits, human in the loop,
prepare-and-stop. NO detection evasion (randomised delays to avoid bot flags): that conflicts
with platform terms and with the locked rules.

**External "Chunk 0.1" (pyproject + config rewrite) — NOT adopted as written:**

1. Too many changes in one chunk (breaks one-change-per-slice).
2. Added unused deps (`textual`, `rapidfuzz`) and lowered the `python-dotenv` bound for no reason.
3. `config show` would print keyring-stored keys as "Missing" (commands.py only knows vault/system).
4. `hydrate_env()` / `get_credential_status()` would query the OS keychain for ~12 variables on
   every command (slow; macOS may prompt) → keyring must be lazy, active backend only.
5. Base URLs (settings, not secrets) were put in keyring/vault → belong in `config.toml` (`api_base`).
6. "Dynamic providers" claimed, yet `set-backend` still rejects anything outside a fixed list and a
   hardcoded provider→env table remains. litellm 1.104.2 ships `validate_environment(model,
api_key, api_base, api_version)` (exists; behaviour NOT yet tested) → candidate replacement.
7. **ERRATUM to Log 12:** the "chmod race / create .env 0600 first" fix is WITHDRAWN. Tested:
   python-dotenv's `set_key` already creates the file 0600 and keeps 0600 on rewrite, so there is
   no permission window with python-dotenv >=1.2. (Lesson: test a reviewer's "real defect" claim
   before adopting it — three reviewers, including this architect, repeated it untested.)

**Done:** 0a `pyproject.toml` — python>=3.11, `tomli` removed, `pathspec>=1.0`,
`graphifyy>=0.9.95,<0.10` (0.9.95 verified to exist, Apache-2.0), dev extra `pytest`, pytest config
(`pythonpath=src`). 0b `config.py` — stdlib `tomllib`; `save_config` uses `exclude_defaults=True`.
`tests/test_config.py` (5 tests, passing). Deliberately NOT added yet: `textual`, `rapidfuzz`,
`keyring`, `platformdirs`.
**Next:** 0c `ignore.py` (utf-8, pruned `os.walk`, `"gitignore"`, `write_graphifyignore`, delete
`treewalk`). Later named slices: provider layer (dynamic, `api_base`/`api_key_env` in config.toml),
keyring (lazy, handles a "keyring" source in `config show`).
