PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL,
 age INTEGER CHECK(age IS NULL OR age BETWEEN 13 AND 100),
 telegram_id INTEGER UNIQUE,
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
 must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS restaurants (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, district TEXT NOT NULL,
 restaurant_type TEXT NOT NULL, average_price INTEGER NOT NULL CHECK(average_price >= 0),
 address TEXT, description TEXT, source TEXT,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 action TEXT NOT NULL, selected_district TEXT, selected_type TEXT,
 selected_budget INTEGER, recommended_restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE RESTRICT,
 details TEXT, created_at TEXT NOT NULL
);
-- Ownership persists across logout; users.telegram_id represents an active session.
CREATE TABLE IF NOT EXISTS account_owners (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 telegram_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
 admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 table_name TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
 delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
 UNIQUE(event_id, admin_id)
);
CREATE TABLE IF NOT EXISTS login_attempts (
 telegram_id INTEGER PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, locked_until TEXT
);
