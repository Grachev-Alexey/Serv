-- Виви · миграция: доступ выдаётся сетью (человек = одна сеть студий)
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS network VARCHAR(128) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_users_network ON users (network);

-- Студии без сети — это сеть «ВИВИ».
UPDATE studios SET network = 'ВИВИ' WHERE coalesce(btrim(network), '') = '';

DROP TABLE IF EXISTS user_studios;

COMMIT;

SELECT coalesce(nullif(network,''),'—') AS network, count(*) AS studios
FROM studios GROUP BY 1 ORDER BY 1;
SELECT username, is_admin, coalesce(nullif(network,''),'—') AS network FROM users ORDER BY username;
