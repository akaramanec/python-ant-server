# SmartFizruk Server (ANT+ Gym Dashboard)

Серверна частина для фітнес-залу: приймає пульс з "слухачів" (Raspberry/Orange Pi), зберігає дані в SQLite та показує live-дашборд на TV/моніторі.

Поточна версія включає:
- прийом телеметрії `device_id + hr + ts` через API;
- live-оновлення дашборду через WebSocket;
- облік оренди трекерів (початок/завершення);
- автододавання нових трекерів (керується через `settings`);
- статус сигналу на картках (`На зв'язку / Відсутній сигнал / Незв'язаний`);
- таймаут сигналу з налаштування (`tracking_timeout_sec`);
- бекап SQLite через `backup_db.sh`.

## Як працює потік даних

1. Listener-и надсилають події на `POST /log`.
2. Сервер робить дедуплікацію за парою `(device_id, timestamp)`.
3. Якщо увімкнено пошук нових трекерів, новий `device_id` автоматично додається в `trackers`.
4. Для активної оренди оновлюються пульс, час тренування, калорії.
5. Дашборд отримує live-події по WebSocket (`/ws`).
6. При завершенні оренди сервер шле подію, і картка зникає з UI.

## 1) Вимоги (Raspberry Pi / Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 git
```

## 2) Отримання проєкту

```bash
cd ~
git clone <YOUR_REPO_URL> ant_server
cd ant_server
```

Або якщо папка вже існує і треба примусово оновити до `origin/main`:

```bash
cd ~/ant_server
git fetch origin
git reset --hard origin/main
git clean -fd
```

## 3) Встановлення залежностей

```bash
cd ~/ant_server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn jinja2 requests python-dotenv
```

## 4) Налаштування `.env`

```bash
cat > .env <<'EOF'
API_KEY=my_secret_key_123
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
DB_PATH=heart_data.db
EOF
```

## 5) Ініціалізація БД

```bash
cd ~/ant_server
python3 -c "import database; database.init_db(); print('DB init done')"
```

Перевірити, що ключові таблиці є:

```bash
python3 -c "import sqlite3, config; conn=sqlite3.connect(config.DB_FILE); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]); conn.close()"
```

## 6) Запуск сервера

```bash
cd ~/ant_server
source .venv/bin/activate
python3 server.py
```

Після запуску:
- Dashboard: `http://<SERVER_IP>:8000/`
- API логів: `POST /log` (з `X-API-Key`)

## 7) Systemd автозапуск

```bash
sudo tee /etc/systemd/system/ant_server.service > /dev/null <<EOF
[Unit]
Description=SmartFizruk FastAPI Server
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=/home/$(whoami)/ant_server
ExecStart=/home/$(whoami)/ant_server/.venv/bin/python /home/$(whoami)/ant_server/server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ant_server.service
sudo systemctl restart ant_server.service
sudo systemctl status ant_server.service
```

Швидкий перезапуск (локальний скрипт):

```bash
bash reload_demon.sh
```

## 8) Бекап БД

У проєкті є `backup_db.sh`.

Ручний запуск:

```bash
cd ~/ant_server
bash backup_db.sh
```

Cron (щодня о 03:00):

```bash
crontab -e
```

Додати рядок:

```cron
0 3 * * * /home/admin/ant_server/backup_db.sh >> /home/admin/ant_server/backups/backup.log 2>&1
```

## 9) Тестові користувачі

Для seed 20+ користувачів:

```bash
cd ~/ant_server
python3 migration_seed_test_users.py
```

## 10) Корисні API

- `POST /log` - прийом пульсу від listener
- `POST /users/register` - додати користувача
- `POST /rentals/start` - почати/продовжити оренду за сьогодні
- `POST /rentals/stop` - завершити оренду
- `GET /settings/search-new-trackers`
- `PUT /settings/search-new-trackers`
- `GET /dashboard/users`
- `GET /dashboard/trackers`
- `GET /dashboard/rentals/status`
- `POST /dashboard/rentals/start`
- `POST /dashboard/rentals/stop`

## 11) Troubleshooting

- **Порожній дашборд**: перевірити, чи є активні оренди в `device_rentals`.
- **Не приймає `/log`**: перевірити `X-API-Key` і значення в `.env`.
- **Не видно live-оновлень**: перевірити WebSocket `/ws` і статус сервісу `ant_server.service`.
- **Картка не зникає після stop**: переконатися, що оновлений `server.py` розгорнуто і сервіс перезапущено.
