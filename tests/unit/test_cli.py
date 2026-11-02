from typer.testing import CliRunner
from quimia_ingestion.cli import app

runner = CliRunner()


def test_bridge_status_pending_without_credentials():
    result = runner.invoke(app, ["bridge-status"])
    assert result.exit_code == 0
    assert "optional-not-configured" in result.stdout


def test_ingest_public_requires_explicit_db_write():
    result = runner.invoke(app, ["ingest-public"])
    assert result.exit_code != 0
    assert "--write-db" in (result.stdout + getattr(result, "stderr", ""))
