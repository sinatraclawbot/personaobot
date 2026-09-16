import os
from pathlib import Path
import subprocess
import sys


def test_migration_upgrade_check_and_downgrade(tmp_path):
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + str(tmp_path / "migration.db")}
    root = Path(__file__).resolve().parents[1]
    for args in [("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head")]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=root, env=env, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
