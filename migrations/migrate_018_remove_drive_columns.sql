-- Видалення Drive-специфічних колонок (Drive sync видалено повністю)
ALTER TABLE attachments DROP COLUMN IF EXISTS drive_id;
ALTER TABLE attachments DROP COLUMN IF EXISTS storage_type;
ALTER TABLE users      DROP COLUMN IF EXISTS refresh_token;
