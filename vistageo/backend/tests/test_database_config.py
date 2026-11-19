import pytest

from app import database


def use_env_file(monkeypatch, tmp_path, content):
    monkeypatch.setattr(database, "__file__", str(tmp_path / "app" / "database.py"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("DATABASE_URL")
    (tmp_path / ".env").write_text(content, encoding="utf-8")


def test_database_url_loads_local_env_without_interpolation(monkeypatch, tmp_path):
    url = "postgresql+psycopg://user:${PASSWORD}@example.invalid/db"
    use_env_file(monkeypatch, tmp_path, f"DATABASE_URL={url}\n")
    assert database.database_url() == url


def test_environment_takes_precedence_over_local_file(monkeypatch, tmp_path):
    use_env_file(monkeypatch, tmp_path, "DATABASE_URL=postgresql+psycopg://local/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://external/db")
    assert database.database_url() == "postgresql+psycopg://external/db"


@pytest.mark.parametrize("content", ["", "DATABASE_URL=sqlite:///local.db\n"])
def test_database_url_rejects_missing_or_invalid_config(monkeypatch, tmp_path, content):
    use_env_file(monkeypatch, tmp_path, content)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database.database_url()
