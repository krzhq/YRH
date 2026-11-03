import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
from app.services.security import RESERVED, hasher, valid_age, valid_password, valid_username, verify

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, path: str):
        self.path = str(path)

    @asynccontextmanager
    async def connect(self):
        async with aiosqlite.connect(self.path, timeout=15) as db:
            db.row_factory = aiosqlite.Row
            await db.execute('PRAGMA foreign_keys=ON')
            await db.execute('PRAGMA busy_timeout=15000')
            yield db

    async def initialize(self, initial_password: str):
        if not valid_password(initial_password):
            raise ValueError('ADMIN_INITIAL_PASSWORD must contain 8–128 characters')
        async with self.connect() as db:
            await db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            await self._migrate_account_owners(db)
            for name in RESERVED:
                existing = await (await db.execute('SELECT role FROM users WHERE username=?', (name,))).fetchone()
                if existing and existing['role'] != 'admin':
                    raise ValueError('Reserved administrator username belongs to a non-admin account')
                if not existing:
                    stamp = now()
                    await db.execute('INSERT INTO users(username,password_hash,role,must_change_password,created_at,updated_at) VALUES(?,?,?,0,?,?)', (name, hasher.hash(initial_password), 'admin', stamp, stamp))
            await db.commit()

    async def _migrate_account_owners(self, db):
        # Old databases allowed each Telegram identity to own only one account.
        # Preserve the reverse restriction: an account has exactly one owner.
        indexes = await (await db.execute("PRAGMA index_list('account_owners')")).fetchall()
        old_constraint = False
        for index in indexes:
            if not index['unique']:
                continue
            columns = await (await db.execute('SELECT name FROM pragma_index_info(?)', (index['name'],))).fetchall()
            if [row['name'] for row in columns] == ['telegram_id']:
                old_constraint = True
                break
        if not old_constraint:
            return
        backup_path = self.path + '.before-owners-migration.bak'
        if Path(backup_path).exists():
            backup_path = self.path + '.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.bak'
        async with aiosqlite.connect(backup_path) as backup:
            await db.backup(backup)
        try:
            await db.execute('BEGIN IMMEDIATE')
            await db.execute('CREATE TABLE account_owners_new (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, telegram_id INTEGER NOT NULL)')
            await db.execute('INSERT INTO account_owners_new SELECT user_id,telegram_id FROM account_owners')
            await db.execute('DROP TABLE account_owners')
            await db.execute('ALTER TABLE account_owners_new RENAME TO account_owners')
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def _outbox(self, db, table: str, payload: dict):
        event = uuid.uuid4().hex
        await db.execute("INSERT INTO notification_outbox(event_id,admin_id,table_name,payload,created_at) SELECT ?,id,?,?,? FROM users WHERE role='admin'", (event, table, json.dumps(payload, ensure_ascii=False), now()))

    async def register(self, username: str, password_hash: str, age: int, telegram_id: int):
        if not valid_username(username) or not valid_age(str(age)) or not password_hash.startswith('$argon2id$'):
            raise ValueError('Invalid registration')
        async with self.connect() as db:
            try:
                await db.execute('BEGIN IMMEDIATE')
                stamp = now()
                cur = await db.execute("INSERT INTO users(username,password_hash,age,telegram_id,role,created_at,updated_at) VALUES(?,?,?,?,'user',?,?)", (username, password_hash, age, telegram_id, stamp, stamp))
                uid = cur.lastrowid
                await db.execute('INSERT INTO account_owners(user_id,telegram_id) VALUES(?,?)', (uid, telegram_id))
                await self._outbox(db, 'users', {'id': uid, 'username': username, 'age': age, 'role': 'user', 'time': stamp})
                await db.commit()
                return uid
            except Exception:
                await db.rollback()
                raise

    async def insert_restaurant(self, name, district, restaurant_type, average_price, address=None, description=None, source=None):
        async with self.connect() as db:
            stamp = now()
            cur = await db.execute('INSERT INTO restaurants(name,district,restaurant_type,average_price,address,description,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)', (name,district,restaurant_type,average_price,address,description,source,stamp,stamp))
            await self._outbox(db, 'restaurants', {'id':cur.lastrowid,'name':name,'district':district,'average_price':average_price,'time':stamp})
            await db.commit()
            return cur.lastrowid

    async def insert_log(self, user_id, action, selected_district=None, selected_type=None, selected_budget=None, recommended_restaurant_id=None, details=None):
        async with self.connect() as db:
            stamp = now()
            cur = await db.execute('INSERT INTO logs(user_id,action,selected_district,selected_type,selected_budget,recommended_restaurant_id,details,created_at) VALUES(?,?,?,?,?,?,?,?)', (user_id,action,selected_district,selected_type,selected_budget,recommended_restaurant_id,details,stamp))
            await self._outbox(db, 'logs', {'id':cur.lastrowid,'user_id':user_id,'action':action,'budget':selected_budget,'time':stamp})
            await db.commit()
            return cur.lastrowid

    async def get_user(self, telegram_id):
        async with self.connect() as db:
            return await (await db.execute('SELECT * FROM users WHERE telegram_id=?', (telegram_id,))).fetchone()

    async def username_exists(self, username):
        async with self.connect() as db:
            return bool(await (await db.execute('SELECT 1 FROM users WHERE username=?', (username,))).fetchone())

    async def login(self, username, password, telegram_id):
        async with self.connect() as db:
            await db.execute('BEGIN IMMEDIATE')
            attempt = await (await db.execute('SELECT * FROM login_attempts WHERE telegram_id=?', (telegram_id,))).fetchone()
            if attempt and attempt['locked_until'] and attempt['locked_until'] > now():
                await db.rollback()
                return 'locked'
            user = await (await db.execute('SELECT * FROM users WHERE username=?', (username,))).fetchone()
            if not user or not verify(user['password_hash'], password):
                failures = (attempt['failures'] if attempt and not attempt['locked_until'] else 0) + 1
                until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat() if failures >= 5 else None
                await db.execute('INSERT INTO login_attempts VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET failures=excluded.failures,locked_until=excluded.locked_until', (telegram_id, failures, until))
                await db.commit()
                return 'locked' if until else 'invalid'
            owner = await (await db.execute('SELECT telegram_id FROM account_owners WHERE user_id=?', (user['id'],))).fetchone()
            if owner and owner['telegram_id'] != telegram_id:
                await db.rollback()
                return 'linked'
            active = await (await db.execute('SELECT id FROM users WHERE telegram_id=?', (telegram_id,))).fetchone()
            if active and active['id'] != user['id']:
                await db.rollback()
                return 'active'
            await db.execute('INSERT OR IGNORE INTO account_owners VALUES(?,?)', (user['id'], telegram_id))
            await db.execute('UPDATE users SET telegram_id=?, updated_at=? WHERE id=?', (telegram_id, now(), user['id']))
            await db.execute('DELETE FROM login_attempts WHERE telegram_id=?', (telegram_id,))
            await db.commit()
            return 'ok'

    async def logout(self, telegram_id):
        async with self.connect() as db:
            exists = await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tinder_sessions'")).fetchone()
            if exists:
                await db.execute("UPDATE tinder_sessions SET status='ended',ended_at=? WHERE status='active' AND user_id IN (SELECT id FROM users WHERE telegram_id=?)", (now(),telegram_id))
            await db.execute('UPDATE users SET telegram_id=NULL,updated_at=? WHERE telegram_id=?', (now(),telegram_id))
            await db.commit()

    async def change_password(self, telegram_id, password):
        if not valid_password(password):
            raise ValueError('Invalid password')
        async with self.connect() as db:
            await db.execute('UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE telegram_id=?', (hasher.hash(password), now(),telegram_id))
            await db.commit()

    async def verify_current_password(self, telegram_id, password):
        async with self.connect() as db:
            await db.execute('BEGIN IMMEDIATE')
            user = await (await db.execute('SELECT id,password_hash FROM users WHERE telegram_id=?', (telegram_id,))).fetchone()
            if not user:
                await db.rollback()
                return 'unauthenticated'
            attempt = await (await db.execute('SELECT * FROM login_attempts WHERE telegram_id=?', (telegram_id,))).fetchone()
            if attempt and attempt['locked_until'] and attempt['locked_until'] > now():
                await db.rollback()
                return 'locked'
            if not verify(user['password_hash'], password):
                failures = (attempt['failures'] if attempt and not attempt['locked_until'] else 0) + 1
                until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat() if failures >= 5 else None
                await db.execute('INSERT INTO login_attempts VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET failures=excluded.failures,locked_until=excluded.locked_until', (telegram_id, failures, until))
                await db.commit()
                return 'locked' if until else 'invalid'
            await db.execute('DELETE FROM login_attempts WHERE telegram_id=?', (telegram_id,))
            await db.commit()
            return user['password_hash']

    async def update_password_hash(self, telegram_id, expected_hash, new_hash):
        async with self.connect() as db:
            cur = await db.execute('UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE telegram_id=? AND password_hash=?', (new_hash, now(), telegram_id, expected_hash))
            await db.commit()
            return cur.rowcount == 1

    async def delete_account(self, telegram_id):
        async with self.connect() as db:
            user = await (await db.execute('SELECT id,role FROM users WHERE telegram_id=?', (telegram_id,))).fetchone()
            if not user or user['role'] == 'admin':
                return False
            try:
                await db.execute('DELETE FROM users WHERE id=?', (user['id'],))
                await db.commit()
                return True
            except sqlite3.IntegrityError:
                await db.rollback()
                return False

    async def stats(self):
        async with self.connect() as db:
            result = {}
            for name in ('users','restaurants','logs'):
                result[name] = (await (await db.execute(f'SELECT COUNT(*) FROM {name}')).fetchone())[0]
            result['admins'] = (await (await db.execute("SELECT COUNT(*) FROM users WHERE role='admin'")).fetchone())[0]
            return result

    async def users_page(self, offset):
        async with self.connect() as db:
            return await (await db.execute('SELECT username,role FROM users ORDER BY id LIMIT 10 OFFSET ?', (offset,))).fetchall()

    async def recent_logs(self):
        async with self.connect() as db:
            return await (await db.execute('SELECT user_id,action,created_at FROM logs ORDER BY id DESC LIMIT 10')).fetchall()

