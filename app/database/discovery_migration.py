"""Preserve existing SQLite IDs and foreign keys while extending restaurant data."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RESTAURANT_SQL = '''CREATE TABLE restaurants_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, district TEXT,
 restaurant_type TEXT NOT NULL, average_price INTEGER CHECK(average_price IS NULL OR average_price >= 0),
 address TEXT, description TEXT, source TEXT, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 original_json_id TEXT, site_id TEXT, external_key TEXT, categories TEXT,
 capacity INTEGER, landmark TEXT, latitude REAL, longitude REAL, rating REAL, reviews_count INTEGER,
 average_bill TEXT, price_min INTEGER, price_max INTEGER, price_midpoint INTEGER,
 phone TEXT, instagram TEXT, website TEXT, working_hours TEXT, status_now TEXT,
 menu_vibe TEXT, color_palette_hex TEXT, photo TEXT, photos TEXT, page_url TEXT, raw_json TEXT
)'''

def migrate(path: str | Path) -> str | None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'База данных не найдена: {path}')
    with sqlite3.connect(path, timeout=30) as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(restaurants)')}
        if not columns:
            raise RuntimeError('Таблица restaurants отсутствует; сначала запустите приложение')
        if 'external_key' in columns:
            return None
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_path = path.with_name(path.name + f'.before-discovery-{stamp}.bak')
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Не удалось проверить резервную копию')
        db.execute('PRAGMA foreign_keys=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute(RESTAURANT_SQL)
            old_columns = 'id,name,district,restaurant_type,average_price,address,description,source,is_active,created_at,updated_at'
            db.execute(f'INSERT INTO restaurants_new ({old_columns}) SELECT {old_columns} FROM restaurants')
            db.execute('DROP TABLE restaurants')
            db.execute('ALTER TABLE restaurants_new RENAME TO restaurants')
            db.execute('CREATE UNIQUE INDEX restaurant_external_key ON restaurants(external_key)')
            db.execute('CREATE INDEX restaurant_district_idx ON restaurants(district)')
            db.execute('CREATE INDEX restaurant_type_idx ON restaurants(restaurant_type)')
            db.execute('CREATE INDEX restaurant_price_idx ON restaurants(price_min,price_max)')
            violations = db.execute('PRAGMA foreign_key_check').fetchall()
            if violations:
                raise RuntimeError(f'Нарушены внешние ключи: {violations[:3]}')
            db.commit()
        except Exception:
            db.rollback()
            raise
        return str(backup_path)
