"""마이그레이션만으로 만든 SQLite DB에서 시각 기본값이 동작하는지 확인함.

테스트 DB는 모델(create_all)로 만들기 때문에, 마이그레이션의 server_default가
SQLite에서 못 쓰는 함수(now())여도 다른 테스트로는 드러나지 않음.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_upgrade_head_on_sqlite_fills_timestamps(tmp_path):
    db = tmp_path / "migrated.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db.as_posix()}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workflow_facility_accounts"
            " (facility_key, company_id, verification_reference, synthetic)"
            " VALUES ('f', 'c', 'test', 1)"
        )
        created, updated = conn.execute(
            "SELECT created_at, updated_at FROM workflow_facility_accounts"
        ).fetchone()
    assert created and updated
