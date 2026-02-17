-- Theme profiles (Anish, Loveleet, or custom) per user. UI settings are scoped by (user_id, theme_profile_id).
-- Run after users/sessions exist. ui_settings will get theme_profile_id column via server migration.

CREATE TABLE IF NOT EXISTS theme_profiles (
  id         SERIAL PRIMARY KEY,
  user_id    TEXT NOT NULL,
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_theme_profiles_user ON theme_profiles(user_id);

-- Optional: seed default profiles for existing users (run once).
-- INSERT INTO theme_profiles (user_id, name)
-- SELECT DISTINCT id::text, 'Anish' FROM users
-- ON CONFLICT (user_id, name) DO NOTHING;
-- INSERT INTO theme_profiles (user_id, name)
-- SELECT DISTINCT id::text, 'Loveleet' FROM users
-- ON CONFLICT (user_id, name) DO NOTHING;
