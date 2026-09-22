-- ═══════════════════════════════════════════════════════════════════════════
-- Виви · миграция 2026-09-08
--   1) мультиаккаунтинг: студии, привязка камер, права пользователей
--   2) часовой пояс — свойство студии (вычислен из данных)
--   3) недостающие индексы из models.py
--   4) удаление мусорного устройства (Windows Sandbox)
-- Выполнять целиком: всё в одной транзакции, при ошибке откатится.
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

-- ── 1. Схема ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS studios (
    id         serial PRIMARY KEY,
    name       varchar(128) NOT NULL,
    network    varchar(128) NOT NULL DEFAULT '',   -- «НЕЖНО»; пусто — одиночная студия
    tz         varchar(64)  NOT NULL DEFAULT 'Europe/Moscow',
    created_at timestamp    NOT NULL DEFAULT (now() at time zone 'utc')
);

ALTER TABLE devices ADD COLUMN IF NOT EXISTS studio_id integer REFERENCES studios(id);
ALTER TABLE users   ADD COLUMN IF NOT EXISTS is_admin  boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS user_studios (
    username  varchar(64) NOT NULL,
    studio_id integer     NOT NULL REFERENCES studios(id) ON DELETE CASCADE,
    PRIMARY KEY (username, studio_id)
);

CREATE INDEX IF NOT EXISTS ix_devices_studio        ON devices (studio_id);
CREATE INDEX IF NOT EXISTS ix_user_studios_username ON user_studios (username);

-- индексы, объявленные в models.py, но не созданные (колонки добавлялись через ALTER)
CREATE INDEX IF NOT EXISTS ix_segments_event ON segments (event);
CREATE INDEX IF NOT EXISTS ix_segments_idle  ON segments (idle);

-- ── 2. Мусорное устройство (Windows Sandbox, WDAGUtilityAccount) ───────────
DELETE FROM screen_events WHERE device_id = '6c5fe7fc-a9c6-46cd-baea-529d2dedc1df';
DELETE FROM conversations WHERE device_id = '6c5fe7fc-a9c6-46cd-baea-529d2dedc1df';
DELETE FROM transcripts   WHERE device_id = '6c5fe7fc-a9c6-46cd-baea-529d2dedc1df';
DELETE FROM segments      WHERE device_id = '6c5fe7fc-a9c6-46cd-baea-529d2dedc1df';
DELETE FROM devices       WHERE device_id = '6c5fe7fc-a9c6-46cd-baea-529d2dedc1df';

-- ── 3. Студии из текущих камер ─────────────────────────────────────────────
-- Часовые пояса вычислены из данных: сравнение времени в имени файла
-- (ffmpeg -strftime, локальное время камеры) с start_ts по «живым» загрузкам.
-- Все смещения легли ровно в целые часы. Белорусская — подтверждена вручную.
INSERT INTO studios (name, network, tz) VALUES
    ('Садовая',              '',       'Europe/Moscow'),
    ('Пионерская',           '',       'Europe/Moscow'),
    ('Пролетарская (лазер)', 'НЕЖНО',  'Europe/Moscow'),
    ('Белорусская (лазер)',  'НЕЖНО',  'Europe/Moscow'),
    ('Екатеринбург',         '',       'Asia/Yekaterinburg'),
    ('Уфа',                  '',       'Asia/Yekaterinburg'),
    ('Омск',                 '',       'Asia/Omsk'),
    ('Новосибирск',          '',       'Asia/Novosibirsk')
ON CONFLICT DO NOTHING;

-- Привязка: по хвосту friendly_name после «/» (или по всему имени).
UPDATE devices d SET studio_id = s.id
FROM studios s
WHERE d.studio_id IS NULL
  AND btrim(split_part(d.friendly_name, '/', greatest(1, array_length(string_to_array(d.friendly_name,'/'),1)))) = s.name;

-- ── 4. Админ видит всё ─────────────────────────────────────────────────────
UPDATE users SET is_admin = true WHERE username = 'vivi-admin';

COMMIT;

-- ── Проверка ───────────────────────────────────────────────────────────────
SELECT s.id, coalesce(nullif(s.network,'')||' / ','')||s.name AS studio, s.tz,
       count(d.device_id) AS cameras
FROM studios s LEFT JOIN devices d ON d.studio_id = s.id
GROUP BY 1,2,3 ORDER BY s.network, s.name;

SELECT count(*) AS "камер без студии" FROM devices WHERE studio_id IS NULL;
