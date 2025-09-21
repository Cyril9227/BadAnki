-- Create the users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

-- Create the cards table
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    last_reviewed TIMESTAMP,
    repetition_level INTEGER NOT NULL DEFAULT 0,
    easiness_factor REAL NOT NULL DEFAULT 2.5,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Create the courses table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    content TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, path),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Create the user_api_keys table
CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id INTEGER PRIMARY KEY,
    gemini_api_key TEXT,
    anthropic_api_key TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Create the user_secrets table
CREATE TABLE IF NOT EXISTS user_secrets (
    user_id INTEGER PRIMARY KEY,
    telegram_chat_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
);
