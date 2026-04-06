from pathlib import Path


def get_database_path() -> Path:
    """Return the default SQLite database path for local development."""
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "data" / "seed" / "curriculum_advisor.db"
