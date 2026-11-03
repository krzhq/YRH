import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def migrate_release(path):
    path=Path(path)
    if not path.exists(): raise FileNotFoundError(path)
    with sqlite3.connect(path, timeout=30) as db:
        cols={row[1] for row in db.execute('PRAGMA table_info(recommendation_feedback)')}
        if not cols: raise RuntimeError('MVP migration is required first')
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quiz_state'").fetchone()
        if 'reason' in cols and exists: return None
        backup=path.with_name(path.name+'.before-release-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.bak')
        with sqlite3.connect(backup) as dst:
            db.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Backup integrity check failed')
        try:
            db.execute('BEGIN IMMEDIATE')
            if 'reason' not in cols: db.execute('ALTER TABLE recommendation_feedback ADD COLUMN reason TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS quiz_state (state_key TEXT PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL)')
            if db.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('Foreign key check failed')
            db.commit()
        except Exception:
            db.rollback(); raise
        return str(backup)
