CREATE TABLE IF NOT EXISTS statistics (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE RESTRICT,
 recommendation_session_id INTEGER NOT NULL REFERENCES recommendation_sessions(id) ON DELETE RESTRICT,
 recommendation_result_id INTEGER NOT NULL REFERENCES recommendation_results(id) ON DELETE RESTRICT,
 stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
 feedback_reason TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(user_id,recommendation_result_id)
);
CREATE INDEX IF NOT EXISTS idx_statistics_updated ON statistics(updated_at);
CREATE INDEX IF NOT EXISTS idx_statistics_restaurant ON statistics(restaurant_id);
