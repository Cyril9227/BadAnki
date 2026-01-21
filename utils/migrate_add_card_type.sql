-- Migration: Add card_type column to cards table
-- Run this migration when you're ready to persist card_type in the database.
--
-- Currently, the application detects cloze cards by pattern matching {{c1::...}} in the question field.
-- After running this migration, card_type will be stored explicitly.

-- Add the card_type column with a default of 'basic'
ALTER TABLE cards ADD COLUMN IF NOT EXISTS card_type VARCHAR(10) DEFAULT 'basic';

-- Optional: Update existing cloze cards based on pattern detection
-- This will set card_type='cloze' for any cards that have the cloze syntax in their question
UPDATE cards
SET card_type = 'cloze'
WHERE question ~ '\{\{c[0-9]+::[^}]+\}\}' AND card_type = 'basic';

-- Create an index for filtering by card_type (optional, for performance)
CREATE INDEX IF NOT EXISTS idx_cards_card_type ON cards(card_type);
