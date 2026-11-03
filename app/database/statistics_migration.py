"""One-way migration; the legacy feedback table is preserved read-only."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def migrate_statistics(path):
    path=Path(path)
    if not path.exists(): raise FileNotFoundError(path)
    with sqlite3.connect(path,timeout=30) as db:
        db.execute('PRAGMA foreign_keys=ON')
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='statistics'").fetchone()
        if exists:
            return {'backup':None,'migrated':0,'total':db.execute('SELECT count(*) FROM statistics').fetchone()[0]}
        legacy_columns={r[1] for r in db.execute('PRAGMA table_info(recommendation_feedback)')}
        if not {'user_id','result_id','rating','created_at','updated_at'}.issubset(legacy_columns):
            raise RuntimeError('Expected recommendation_feedback schema was not found')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_path=path.with_name(path.name+'.before-statistics-'+stamp+'.bak')
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Backup integrity check failed')
        try:
            db.execute('BEGIN IMMEDIATE')
            invalid=db.execute('''SELECT COUNT(*) FROM recommendation_feedback f
                LEFT JOIN recommendation_results r ON r.id=f.result_id
                LEFT JOIN recommendation_sessions s ON s.id=r.session_id
                WHERE r.id IS NULL OR s.id IS NULL OR s.user_id!=f.user_id OR s.status!='completed'
                   OR f.rating NOT BETWEEN 1 AND 5''').fetchone()[0]
            if invalid: raise RuntimeError(f'{invalid} legacy feedback rows have invalid ownership or session state')
            schema=Path(__file__).with_name('statistics_schema.sql').read_text(encoding='utf-8')
            for statement in schema.split(';'):
                if statement.strip(): db.execute(statement)
            reason='f.reason' if 'reason' in legacy_columns else 'NULL'
            cur=db.execute(f'''INSERT INTO statistics(user_id,restaurant_id,recommendation_session_id,recommendation_result_id,stars,feedback_reason,created_at,updated_at)
                SELECT f.user_id,r.restaurant_id,r.session_id,f.result_id,f.rating,{reason},f.created_at,f.updated_at
                FROM recommendation_feedback f JOIN recommendation_results r ON r.id=f.result_id''')
            migrated=cur.rowcount
            # Cross-table relationships must describe the very same completed result.
            for action in ('INSERT','UPDATE'):
                db.execute(f'''CREATE TRIGGER statistics_validate_{action.lower()} BEFORE {action} ON statistics
                    WHEN NOT EXISTS (SELECT 1 FROM recommendation_results r JOIN recommendation_sessions s ON s.id=r.session_id
                        WHERE r.id=NEW.recommendation_result_id AND r.restaurant_id=NEW.restaurant_id
                          AND r.session_id=NEW.recommendation_session_id AND s.user_id=NEW.user_id AND s.status='completed')
                    BEGIN SELECT RAISE(ABORT, 'invalid recommendation ownership'); END''')
            for action in ('INSERT','UPDATE','DELETE'):
                db.execute(f'''CREATE TRIGGER legacy_feedback_readonly_{action.lower()} BEFORE {action} ON recommendation_feedback
                    BEGIN SELECT RAISE(ABORT, 'legacy feedback is read-only; use statistics'); END''')
            if db.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('Foreign key check failed')
            total=db.execute('SELECT COUNT(*) FROM statistics').fetchone()[0]
            db.commit()
        except Exception:
            db.rollback(); raise
        return {'backup':str(backup_path),'migrated':migrated,'total':total}
