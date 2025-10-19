-- Create the profiles table (linked 1:1 to auth.users)
CREATE TABLE IF NOT EXISTS profiles (
    auth_user_id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    telegram_chat_id TEXT,
    gemini_api_key TEXT,
    anthropic_api_key TEXT
);

-- Create the cards table
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    interval INT NOT NULL DEFAULT 0,
    ease_factor FLOAT4 NOT NULL DEFAULT 2.5,
    user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE
);

-- Create the courses table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    content TEXT,
    updated_at TIMESTAMP,
    user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    UNIQUE (user_id, path)
);
