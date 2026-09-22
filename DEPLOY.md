# Виви · Развёртывание в прод (Docker за уже существующим nginx)

На сервере уже есть свой (хостовый) **nginx + certbot** и другие приложения.
Поэтому Виви НЕ поднимает второй nginx на 80/443, а работает так:

```
браузер / камера ──HTTPS──► хостовый nginx (TLS, домен) ──► 127.0.0.1:8080 ──► контейнер web (nginx)
                                                                                  ├─ панель (SPA)
                                                                                  ├─ /api → контейнер backend:8000
                                                                                  └─ /hls → видео-сегменты
```
PostgreSQL уже стоит на сервере — контейнер БД не нужен.
Домен **vivi-control.tw1.ru** привязан к серверу.

## Что в архиве
- `backend/`, `frontend/` — образы (внутри backend ставится ffmpeg)
- `docker-compose.yml` — сервисы `backend` (внутренний) и `web` (слушает 127.0.0.1:8080)
- `deploy/nginx.conf` — конфиг nginx ВНУТРИ контейнера
- `deploy/vivi.host-nginx.conf` — виртуалхост для ХОСТОВОГО nginx (проксирование + место под TLS)
- `.env` — секреты и настройки (уже заполнены)
- `CLIENT.md` — как настроить камеру/клиент

## 1. Docker (один раз)
```
sudo apt update && sudo apt install -y curl
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
docker compose version          # должно быть v2.x
```

## 2. Загрузить и распаковать архив
Через Webmin (**File Manager** / **Upload and Download**) залей `vivi-prod.zip`, например в
`/var/opt/vivi-camera`, и распакуй. `.env` должен лежать рядом с `docker-compose.yml`.

## 3. Запустить стек
```
cd /var/opt/vivi-camera
sudo docker compose up -d --build
```
Стек поднимется и будет слушать только `127.0.0.1:8080` (наружу пока не виден).
Проверка:
```
sudo docker compose ps
curl -I http://127.0.0.1:8080          # ожидаем 200/301 от nginx контейнера
```

> Если раньше уже пытался запустить (и была ошибка «address already in use») —
> сначала `sudo docker compose down --remove-orphans`, затем шаг 3.

## 4. Подключить к хостовому nginx
```
sudo cp deploy/vivi.host-nginx.conf /etc/nginx/sites-available/vivi-control.tw1.ru
sudo ln -s /etc/nginx/sites-available/vivi-control.tw1.ru /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
(Если на сервере нет каталога `sites-available`, положи файл в `/etc/nginx/conf.d/vivi.conf`.)
Виртуалхост уже содержит проброс WebSocket (`/api/ws`) для живых обновлений панели.

Проверить, что порт 8080 свободен под наш стек (если занят другим приложением —
поменяй `8080` в `docker-compose.yml` и в этом виртуалхосте на свободный):
```
sudo ss -tlnp | grep 8080
```

## 5. Включить HTTPS (твой certbot)
```
sudo certbot --nginx -d vivi-control.tw1.ru
```
Certbot получит сертификат Let's Encrypt и сам добавит в виртуалхост 443 + редирект с 80.
Продление у тебя уже автоматическое (системный таймер certbot).

## 6. Открыть панель
`https://vivi-control.tw1.ru/` → вход **vivi-admin / vivimonitoring**.

---

## Обновление версии
Залей новый архив поверх (или изменённые файлы) и:
```
cd /var/opt/vivi-camera
sudo docker compose up -d --build
```
`./storage`, БД и хостовый nginx/сертификат при этом не трогаются.

## Данные и бэкап
- Видео и превью: каталог `./storage` (рядом с compose) — его и бэкапить.
- Индекс сегментов, пользователи, устройства: PostgreSQL (`camera`).

## Безопасность — что стоит сделать
- **Сменить пароль PostgreSQL** (`cd5d56a8` засветился) и закрыть 5432 от интернета.
- `/hls/*.ts` отдаётся без авторизации (плейлисты и экспорт — уже под сессией).
  Если нужно закрыть и сегменты — скажи, добавлю `auth_request`.
