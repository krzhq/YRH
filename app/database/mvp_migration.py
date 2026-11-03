import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def migrate_mvp(path):
    path = Path(path)
    if not path.exists(): raise FileNotFoundError(path)
    with sqlite3.connect(path, timeout=30) as db:
        existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recommendation_sessions'").fetchone()
        if existing: return None
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_path = path.with_name(path.name + '.before-mvp-' + stamp + '.bak')
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('Invalid backup')
        sql = Path(__file__).with_name('mvp_schema.sql').read_text(encoding='utf-8')
        db.executescript('BEGIN IMMEDIATE;\n' + sql + '\nCOMMIT;')
        return str(backup_path)
