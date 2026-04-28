from __future__ import annotations

from pathlib import Path

from backend.config import REPO_ROOT, get_settings


def test_development_defaults_use_repo_data_paths(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("RUN_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_env == "development"
    assert settings.database.path == REPO_ROOT / "data" / "app.db"
    assert settings.run_artifacts.path == REPO_ROOT / "data" / "run_artifacts"
    assert settings.cors_allowed_origins == [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ]

    get_settings.cache_clear()


def test_production_defaults_use_data_volume_paths(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("RUN_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_env == "production"
    assert settings.database.path == Path("/data/app.db")
    assert settings.run_artifacts.path == Path("/data/run_artifacts")
    assert settings.cors_allowed_origins == []

    get_settings.cache_clear()


def test_artifacts_dir_alias_is_supported(monkeypatch) -> None:
    custom_path = "/tmp/custom-run-artifacts"
    monkeypatch.delenv("RUN_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv("ARTIFACTS_DIR", custom_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.run_artifacts.path == Path(custom_path)

    get_settings.cache_clear()
