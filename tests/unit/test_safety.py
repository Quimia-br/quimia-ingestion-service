from pathlib import Path
import subprocess


def test_repo_has_no_git_remote():
    root = Path(__file__).resolve().parents[2]
    output = subprocess.check_output(["git", "remote", "-v"], cwd=root, text=True)
    assert output.strip() == ""


def test_no_remote_github_writer_module_exists():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/quimia_ingestion/integrations/github.py").exists()
