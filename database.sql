-- Description: This script updates the database schema to support multi-user authentication.
--
-- Adds a 'users' table to store user credentials with securely hashed passwords.
-- Adds a 'user_id' foreign key to the 'cards' and 'courses' tables to
-- associate data with specific users, ensuring data isolation.
--
-- Previous versions of this file handled the initial schema creation. This
-- version focuses on the necessary alterations for authentication.

-- Create the users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

-- Add user_id to the cards table
-- Note: If the cards table already contains data, you might need to
-- handle existing rows (e.g., assign them to a default user or handle NULLs).
-- For a new setup, this is straightforward.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);

-- Add user_id to the courses table
ALTER TABLE courses ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
