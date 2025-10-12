-- Create the profiles table (previously users)
CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    telegram_chat_id TEXT,
    gemini_api_key TEXT,
    anthropic_api_key TEXT,
    auth_user_id UUID UNIQUE -- This will link to auth.users(id) in Supabase
);

-- Create the cards table
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    interval INTEGER NOT NULL DEFAULT 0,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    FOREIGN KEY (user_id) REFERENCES profiles (id)
);

-- Create the courses table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    content TEXT,
    updated_at TIMESTAMP,
    UNIQUE (user_id, path),
    FOREIGN KEY (user_id) REFERENCES profiles (id)
);
