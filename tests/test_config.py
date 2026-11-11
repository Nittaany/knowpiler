"""Slice 0b tests: config persistence and credential-source reporting."""
import tomllib

import pytest

from knowpiler.core import config as cfg

CRED_VARS = set(cfg.ENV_VAR_BY_BACKEND.values()) | {"OPENAI_BASE_URL"}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point every config path at a temp dir and clear credential env vars."""
    monkeypatch.setattr(cfg, "KNOWPILER_HOME", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / ".env")
    for var in CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_save_config_writes_only_non_default_values(home):
    cfg.save_config(cfg.Config(backend="gemini"))
    data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert data == {"backend": "gemini"}  # no storage_root / knowledge_root frozen in


def test_load_config_uses_current_defaults_for_unsaved_fields(home):
    cfg.save_config(cfg.Config(backend="ollama", model="llama3"))
    loaded = cfg.load_config()
    assert (loaded.backend, loaded.model) == ("ollama", "llama3")
    assert loaded.storage_root == cfg.Config().storage_root


def test_customised_storage_root_is_still_persisted(home):
    cfg.save_config(cfg.Config(backend="gemini", storage_root="/custom/place"))
    assert cfg.load_config().storage_root == "/custom/place"


def test_credential_status_distinguishes_vault_system_missing(home, monkeypatch):
    (home / ".env").write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    status = cfg.get_credential_status()
    assert status["gemini"]["source"] == "vault"
    assert status["openai"]["source"] == "system"
    assert status["claude"]["source"] == "missing"


def test_save_credential_creates_private_env_file(home):
    cfg.save_credential("GEMINI_API_KEY", "secret")
    env = home / ".env"
    assert "GEMINI_API_KEY" in env.read_text(encoding="utf-8")
    if cfg.os.name != "nt":
        assert (env.stat().st_mode & 0o777) == 0o600

def test_active_project_round_trips_and_clears(tmp_path, monkeypatch):
    from knowpiler.core import config as cfg
    monkeypatch.setattr(cfg, "KNOWPILER_HOME", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config.toml")

    assert cfg.load_config().active_project is None
    cfg.save_config(cfg.Config(active_project="lms"))
    assert cfg.load_config().active_project == "lms"
    cfg.save_config(cfg.Config())
    assert cfg.load_config().active_project is None