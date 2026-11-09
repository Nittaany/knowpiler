"""
Persisted configuration for knowpiler.

Design call: Level-0 (normalize.sh) picked an LLM backend by silently checking env vars in a fixed priority order. Step 4 of the Level-2 pipeline -- the semantic rewrite that resolves contradictions and marks [UNKNOWN] -- is the single most consequential LLM call in the whole system. Which model produced that rewrite is itself part of the traceability record. So: the backend is a config value, set explicitly via `knowpiler config set-backend`, recorded into each project's manifest when `rewrite` runs. Env vars still hold the actual credentials which are stored securely in a local .env file (never in config.toml).
"""
from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path
from typing import Optional

import dotenv
import tomli_w
from pydantic import BaseModel

KNOWPILER_HOME = Path(os.environ.get("KNOWPILER_HOME", Path.home() / ".knowpiler"))
CONFIG_PATH = KNOWPILER_HOME / "config.toml"
ENV_PATH = KNOWPILER_HOME / ".env"

# Project data (staging output, eventually the Layer 1+2 knowledge corpus)
# lives in a *visible* folder, deliberately separate from KNOWPILER_HOME.
# KNOWPILER_HOME starts with a dot -- hidden by default in Finder/Explorer,
# which is fine for config.toml/.env (credential-adjacent, shouldn't be
# casually browsed) but actively hostile for evidence a non-technical user
# needs to find later. Confirmed as a real problem via live `init` testing
# in Level 2.2, not a theoretical one.
KNOWPILER_PROJECTS_HOME = Path(os.environ.get("KNOWPILER_PROJECTS_HOME", Path.home() / "knowpiler-projects"))

SUPPORTED_BACKENDS = ("claude", "gemini", "openai", "deepseek", "kimi", "ollama")

ENV_VAR_BY_BACKEND = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}

# Auto-hydrate process memory with the secure .env file if it exists
def hydrate_env() -> None:
    """Explicitly loads environment variables. Call once at CLI startup."""
    if ENV_PATH.exists():
        dotenv.load_dotenv(ENV_PATH)

class Config(BaseModel):
    backend: Optional[str] = None
    model: Optional[str] = None
    storage_root: str = str(KNOWPILER_PROJECTS_HOME)
    # Unified Layer 1 + Layer 2 corpus -- this is what Level 3/4 will read from.
    knowledge_root: str = str(KNOWPILER_PROJECTS_HOME / "_knowledge")


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    return Config(**data)


def save_config(cfg: Config) -> None:
    KNOWPILER_HOME.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "wb") as f:
        # TOML has no null type, so unset Optional fields are excluded.
        # exclude_defaults also keeps default-derived values (storage_root,
        # knowledge_root) out of the file: writing them froze a stale default
        # into config.toml for good once the default later changed (hit live).
        tomli_w.dump(cfg.model_dump(exclude_none=True, exclude_defaults=True), f)


def backend_ready(backend: str) -> bool:
    """Is the credential this backend needs actually present right now?"""
    env_var = ENV_VAR_BY_BACKEND.get(backend)
    if not env_var:
        return False
    if backend == "ollama":
        return True  # OLLAMA_BASE_URL defaults to localhost if unset
    return bool(os.environ.get(env_var))

def save_credential(env_var: str, value: str) -> None:
    """Securely saves any credential to ~/.knowpiler/.env and updates current session."""
    KNOWPILER_HOME.mkdir(parents=True, exist_ok=True)
    
    # Save the key to the .env file
    dotenv.set_key(ENV_PATH, env_var, value)
    
    # Lock down file permissions: Read/Write for owner ONLY on POSIX systems
    if os.name != "nt":
        ENV_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    
    # Instantly inject it into the running process memory
    os.environ[env_var] = value

def get_vault_status() -> dict:
    """
    Reads the .env file directly from disk. 
    Safe for tests and dry-runs because it never mutates os.environ.
    """
    if not ENV_PATH.exists():
        return {}
    return dotenv.dotenv_values(ENV_PATH)


def get_credential_status() -> dict:
    """Per-backend view of whether a credential is available right now,
    and where it's actually coming from.

    `get_vault_status()` alone isn't enough for an honest status display:
    it only sees ~/.knowpiler/.env, so a credential the user's own shell
    profile exports independently of knowpiler (confirmed real case:
    `export GEMINI_API_KEY=...` in .zshrc) reported as "Missing" even
    though `backend_ready()` -- which checks os.environ -- already treats
    it as ready and silently skips prompting for it during `set-backend`.
    This reconciles the two so `config show` reflects the same truth
    `set-backend` already acts on.

    Three states per backend:
      - "vault":   persisted in ~/.knowpiler/.env -- portable, survives a
                   fresh shell/session or a different machine.
      - "system":  only in os.environ right now -- most likely the user's
                   own shell profile, not anything knowpiler persisted;
                   won't be there in a different terminal/session unless
                   that profile is present there too.
      - "missing": neither.
    """
    vault = get_vault_status()
    status: dict = {}
    for backend, env_var in ENV_VAR_BY_BACKEND.items():
        if backend == "ollama":
            continue
        if vault.get(env_var):
            source = "vault"
        elif os.environ.get(env_var):
            source = "system"
        else:
            source = "missing"
        status[backend] = {"env_var": env_var, "source": source}
    return status


def get_local_base_url_status() -> Optional[tuple]:
    """Where OPENAI_BASE_URL is coming from right now, if anywhere -- same
    vault-vs-system distinction as get_credential_status(), split out
    separately since it isn't tied to one of the standard per-backend
    credential env vars.
    """
    vault = get_vault_status()
    if vault.get("OPENAI_BASE_URL"):
        return vault["OPENAI_BASE_URL"], "vault"
    if os.environ.get("OPENAI_BASE_URL"):
        return os.environ["OPENAI_BASE_URL"], "system"
    return None

def unset_credential(env_var: str) -> None:
    """Removes a credential from the .env vault and current session."""
    if ENV_PATH.exists():
        dotenv.unset_key(ENV_PATH, env_var)
    if env_var in os.environ:
        del os.environ[env_var]