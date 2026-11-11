"""Step 3b-1 tests: direct collection commands over core, with active-project resolution (C11)."""
import pytest
from typer.testing import CliRunner

from knowpiler.cli.commands import app
from knowpiler.core import config as cfg
from knowpiler.core import manifest as mf


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "KNOWPILER_HOME", tmp_path / "home")
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "home" / "config.toml")
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / "home" / ".env")
    cfg.save_config(cfg.Config(storage_root=str(tmp_path / "store")))
    return CliRunner()


def _load(tmp_path):
    return mf.load_manifest("lms", str(tmp_path / "store"))


def test_init_sets_active_project_and_status_needs_no_flag(cli, tmp_path):
    assert cli.invoke(app, ["init", "lms"]).exit_code == 0
    assert cfg.load_config().active_project == "lms"
    r = cli.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "Nothing to analyze" in r.output


def test_no_active_project_and_no_flag_exits_1(cli):
    assert cli.invoke(app, ["status"]).exit_code == 1


def test_init_existing_project_is_confirm_gated(cli):
    assert cli.invoke(app, ["init", "lms"]).exit_code == 0
    assert cli.invoke(app, ["init", "lms"], input="n\n").exit_code == 1
    assert cli.invoke(app, ["init", "lms", "--force"]).exit_code == 0


def test_add_input_add_evidence_and_guarded_remove(cli, tmp_path):
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "README.md").write_text("hi", encoding="utf-8")
    cli.invoke(app, ["init", "lms"])

    assert cli.invoke(app, ["add", "input", str(fe), "--label", "frontend"]).exit_code == 0
    assert cli.invoke(app, ["add", "evidence", str(fe / "README.md"), "--role", "readme"]).exit_code == 0
    m = _load(tmp_path)
    assert [i.label for i in m.inputs] == ["frontend"]
    assert m.evidence[0].scope == ["in-1"]

    assert cli.invoke(app, ["remove", "in-1"]).exit_code == 1  # would widen ev-1's scope
    assert cli.invoke(app, ["remove", "in-1", "--with-evidence"]).exit_code == 0
    m = _load(tmp_path)
    assert m.inputs == [] and m.evidence == []


def test_wrong_type_fails_then_save_as_other_succeeds(cli, tmp_path):
    slides = tmp_path / "deck.pptx"
    slides.write_bytes(b"pptx")
    cli.invoke(app, ["init", "lms"])

    assert cli.invoke(app, ["add", "evidence", str(slides), "--role", "report"]).exit_code == 1
    assert _load(tmp_path).evidence == []

    r = cli.invoke(app, ["add", "evidence", str(slides), "--role", "report", "--save-as-other"])
    assert r.exit_code == 0
    assert _load(tmp_path).evidence[0].role == "other"
    