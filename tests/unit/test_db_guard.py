import sys
import types

import pytest
from typer.testing import CliRunner

from quimia_ingestion import cli
from quimia_ingestion.core import config
from quimia_ingestion.core.config import Settings
from quimia_ingestion.core.exceptions import ConfigurationError
from quimia_ingestion.integrations.postgres import PostgresQuimiaRepository, non_local_db_hosts

AIVEN = "quimia-pg-fake.aivencloud.com"
runner = CliRunner()


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("PGHOSTADDR", "PGSERVICE", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_psycopg(monkeypatch):
    """psycopg falso: registra qualquer tentativa de conexão."""
    calls = []
    module = types.SimpleNamespace(connect=lambda **kw: calls.append(kw) or pytest.fail("conectou ao banco"))
    monkeypatch.setitem(sys.modules, "psycopg", module)
    return calls


def _repo(host):
    return PostgresQuimiaRepository(host=host, port=5432, dbname="quimia", user="u", password="segredo")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "LOCALHOST"])
def test_local_hosts_allowed(host, clean_env, fake_psycopg):
    assert non_local_db_hosts(host) == []
    _repo(host)  # constrói sem conectar
    assert fake_psycopg == []


@pytest.mark.parametrize("host", [AIVEN, "db.example.com", "10.0.0.5", "", "  ", "localhost,db.example.com", "/var/run/postgresql"])
def test_remote_missing_or_unknown_hosts_blocked(host, clean_env, fake_psycopg):
    with pytest.raises(ConfigurationError) as exc:
        _repo(host)
    assert "segredo" not in str(exc.value)
    assert fake_psycopg == []


def test_database_url_remote_not_masked_by_local_host(clean_env, monkeypatch, fake_psycopg):
    monkeypatch.setenv("DATABASE_URL", f"postgres://admin:segredo@{AIVEN}:12345/defaultdb")
    with pytest.raises(ConfigurationError) as exc:
        _repo("localhost")
    assert AIVEN in str(exc.value)
    assert "segredo" not in str(exc.value)
    assert fake_psycopg == []


@pytest.mark.parametrize("name,value", [("PGHOSTADDR", "203.0.113.7"), ("PGSERVICE", "aiven")])
def test_libpq_redirect_env_blocked(clean_env, monkeypatch, fake_psycopg, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        _repo("localhost")


def test_env_takes_precedence_over_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"QUIMIA_DB_HOST={AIVEN}\nQUIMIA_TEST_ONLY_FROM_FILE=x\n", encoding="utf-8")
    monkeypatch.setenv("QUIMIA_DB_HOST", "localhost")
    monkeypatch.delenv("QUIMIA_TEST_ONLY_FROM_FILE", raising=False)
    config._load_dotenv(dotenv)
    import os
    assert os.environ["QUIMIA_DB_HOST"] == "localhost"
    assert os.environ["QUIMIA_TEST_ONLY_FROM_FILE"] == "x"
    monkeypatch.delenv("QUIMIA_TEST_ONLY_FROM_FILE")


def _settings(host):
    return lambda: Settings(db_host=host, db_name="defaultdb", db_password="segredo")


def test_safety_check_fails_on_remote(clean_env, monkeypatch):
    monkeypatch.setattr(cli, "Settings", _settings(AIVEN))
    result = runner.invoke(cli.app, ["safety-check"])
    assert result.exit_code == 1
    assert AIVEN in result.stdout and "REMOTO" in result.stdout
    assert "LOCAL_ONLY" not in result.stdout
    assert "segredo" not in result.stdout


def test_safety_check_passes_on_local(clean_env, monkeypatch):
    monkeypatch.setattr(cli, "Settings", _settings("localhost"))
    result = runner.invoke(cli.app, ["safety-check"])
    assert result.exit_code == 0
    assert "LOCAL_ONLY" in result.stdout


def test_every_db_command_blocked_before_connecting(clean_env, monkeypatch, fake_psycopg, tmp_path):
    monkeypatch.setattr(cli, "Settings", _settings(AIVEN))
    monkeypatch.setattr(cli, "build_public_provider", lambda **kw: object())
    for workflow in ("FDSIngestionWorkflow", "ProductImageWorkflow"):
        monkeypatch.setattr(cli, workflow, lambda **kw: pytest.fail("workflow rodou com banco remoto"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]", encoding="utf-8")
    commands = [
        ["ingest-local", str(manifest)],
        ["ingest-public", "--write-db"],
        ["enrich-images", "--bd-repo", str(tmp_path)],
        ["run-all-local", str(manifest), "--bd-repo", str(tmp_path)],
    ]
    for args in commands:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 2, (args, result.output)
        assert "banco bloqueado" in result.output
        assert "segredo" not in result.output
    assert fake_psycopg == []


def _repo(host, **kw):
    return PostgresQuimiaRepository(host=host, port=1, dbname="d", user="u", password="p", **kw)


def test_remote_host_is_allowed_only_when_named_exactly(clean_env, fake_psycopg):
    assert _repo(AIVEN, allow_remote_host=AIVEN).conninfo["host"] == AIVEN
    for outro in ("outro.aivencloud.com", AIVEN.upper() + ".evil"):
        with pytest.raises(ConfigurationError):
            _repo(outro, allow_remote_host=AIVEN)
    with pytest.raises(ConfigurationError):
        _repo(AIVEN)  # sem permissão explícita continua bloqueado


def test_allowing_the_host_does_not_unblock_env_redirects(clean_env, fake_psycopg, monkeypatch):
    for name, value in (("PGHOSTADDR", "203.0.113.9"), ("PGSERVICE", "prod"), ("DATABASE_URL", "postgres://u@evil.example/db")):
        monkeypatch.setenv(name, value)
        with pytest.raises(ConfigurationError):
            _repo(AIVEN, allow_remote_host=AIVEN)
        monkeypatch.delenv(name)
