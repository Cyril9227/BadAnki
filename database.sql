-- Create the users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    telegram_chat_id TEXT,
    gemini_api_key TEXT,
    anthropic_api_key TEXT
);

-- Create the cards table
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    last_reviewed TIMESTAMP,
    interval INTEGER NOT NULL DEFAULT 0,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Create the courses table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    content TEXT,
    type TEXT NOT NULL, -- 'file' or 'directory'
    updated_at TIMESTAMP,
    UNIQUE (user_id, path),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
