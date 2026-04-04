# SmartFizruk Server (ANT+ Gym Dashboard)

Серверна частина для фітнес-залу: приймає пульс з "слухачів" (Raspberry/Orange Pi), зберігає дані в SQLite та показує live-дашборд на TV/моніторі.

Поточна версія включає:
- прийом телеметрії `device_id + hr + ts` через API;
- **дашборд** (`/`) — публічний (без логіна): лише картки та live через WebSocket `/ws`, без кнопок керування;
- **адмінка** (`/admin`) — оренда, трекери (назва + коефіцієнт корекції пульсу, перемикач пошуку нових трекерів), CRUD користувачів через модалки; пов’язані `GET/POST/PUT` під `/dashboard/*` та сторінка `/admin` потребують у `.env` **обох** змінних `ADMIN_USERNAME` та `ADMIN_PASSWORD` (інакше адмін-зона відповідає **403**); далі — **HTTP Basic Auth**;
- облік оренди трекерів (початок/завершення + resume оренди за поточний день);
- автододавання нових трекерів (керується через `settings`);
- статус сигналу на картках (`На зв'язку / Відсутній сигнал / Незв'язаний`);
- таймаут сигналу з налаштування (`tracking_timeout_sec`);
- бекап SQLite через `backup_db.sh`.

## Шаблони та структура проєкту

**Шаблонізатор:** [Jinja2](https://jinja.palletsprojects.com/) підключається через FastAPI (`fastapi.templating.Jinja2Templates`). У `server.py` каталог шаблонів — **`templates/`**. HTML-сторінки збираються на сервері з підстановкою даних (наприклад `{% for %}`, `{{ змінна }}`, фільтри на кшталт `|default`).

**Де що лежить (коротко):**

| Шлях | Призначення |
|------|-------------|
| `server.py` | Додаток FastAPI: маршрути HTML/API/WebSocket, підключення статики |
| `config.py` | Завантаження `.env` (порт, БД, API-ключ, облікові для адмінки) |
| `database.py` | SQLite: ініціалізація, запити до таблиць |
| `models.py` | Pydantic-моделі для API |
| `utils.py` | Допоміжна логіка (наприклад розрахунок калорій) |
| `rental.py` | Логіка оренди трекерів |
| `web_socket.py` | Розсилка подій клієнтам по WebSocket |
| `templates/` | Jinja2-шаблони: `index.html` (дашборд `/`), `admin.html` (`/admin`) |
| `static/` | Статичні файли; у додатку змонтовано як префікс **`/static`** (`StaticFiles`) |
| `static/css/` | `index.css`, `admin.css` — стилі дашборду та адмінки |
| `static/js/` | `index.js`, `admin.js` — клієнтська логіка (WebSocket, модалки, фільтри) |
| `static/images/` | Зображення для UI (фон, іконки метрик тощо; шлях у шаблонах/CSS — `/static/images/...`) |
| `static/fonts/` | Кастомні шрифти (наприклад `TacticSans*.otf`), підключаються з CSS через `/static/fonts/...` |
| `heart_data.db` | Файл SQLite (ім’я/шлях задається в `.env`, зазвичай `DB_PATH`) |
| `backup_db.sh`, `reload_demon.sh`, `update.sh` | Допоміжні shell-скрипти для сервера |
| `migration_seed_test_users.py` | Опційне заповнення тестовими користувачами |

**Маршрути «сайту» (браузер):** публічно — лише **`/`** (дашборд) та **`/ws`** (WebSocket для live-даних). Сторінка **`/admin`** і JSON API під **`/dashboard/*`** потребують налаштованих `ADMIN_USERNAME` / `ADMIN_PASSWORD` у `.env` і входу по HTTP Basic (деталі — у вступі вище).

## Як працює потік даних

1. Listener-и надсилають події на `POST /log`.
2. Сервер робить дедуплікацію за парою `(device_id, timestamp)`.
3. Якщо увімкнено пошук нових трекерів, новий `device_id` автоматично додається в `trackers`.
4. Для активної оренди оновлюються пульс, час тренування, калорії.
5. Дашборд отримує live-події по WebSocket (`/ws`).
6. При завершенні оренди сервер шле подію, і картка зникає з UI без перезавантаження.
7. При старті оренди система пробує знайти запис за сьогодні для пари `user + tracker` і відновлює його, а не створює дубль.

## 0) Wi‑Fi на сервері (з нуля: Netplan + NetworkManager, як на робочій «Малині»)

**Навіщо:** щоб пристрій отримав IP у Wi‑Fi (дашборд, `POST /log`, SSH) без дроту.

На сучасних **Ubuntu Server** і багатьох збірках **Raspberry Pi OS** мережу керує **NetworkManager**, а стартова конфігурація задається **Netplan** (`/etc/netplan/*.yaml`). У такому режимі **редагування лише** `/etc/wpa_supplicant/wpa_supplicant.conf` **не змінює** підключення: активний профіль береться з **Netplan/NM** (у `nmcli device status` видно на кшталт `netplan-wlan0-<ssid>`).

### 0.1) Що має бути встановлено

Переконайтеся, що Wi‑Fi не заблоковано і встановлені потрібні пакети:

```bash
sudo rfkill unblock wifi
sudo apt update
sudo apt install -y network-manager netplan.io wpasupplicant wireless-tools
sudo systemctl enable --now NetworkManager
```

Перевірка, що саме NM керує інтерфейсом:

```bash
systemctl is-active NetworkManager
nmcli device status
```

Очікується: `wlan0` у стані **connected**, тип **wifi**, колонка **CONNECTION** — ім’я профілю (часто `netplan-wlan0-<назва_ssid>`).

### 0.2) Постійне налаштування через Netplan (рекомендовано)

1. Подивіться файли:

```bash
ls /etc/netplan/
sudo cat /etc/netplan/*.yaml
```

2. Знайдіть файл, де є **`wifis:`** / **`wlan0:`** (інший файл може описувати лише `eth0` — його не змінюйте без потреби).

3. Задайте потрібну мережу в блоці **`access-points`** (SSID і пароль WPA2/WPA3 PSK). Приклад структури (підставте свої `SSID` і пароль; лапки навколо SSID обов’язкові, якщо в назві є пробіли):

```yaml
network:
  version: 2
  wifis:
    wlan0:
      renderer: NetworkManager
      match: {}
      dhcp4: true
      access-points:
        "ВАШ_SSID":
          auth:
            key-management: "psk"
            password: "ПарольАбо64HexВід_wpa_passphrase"
          networkmanager:
            uuid: "..."          # залиште існуючі uuid/name з вашого файла, якщо netplan їх уже створив
            name: "netplan-wlan0-ВАШ_SSID"
            passthrough:
              proxy._: ""
      networkmanager:
        uuid: "..."
        name: "netplan-wlan0-ВАШ_SSID"
```

Пароль можна задати **текстом** або **64 hex** (вивід `wpa_passphrase "SSID" "пароль"` → поле `psk=`).

4. Обмежте права на конфіги та застосуйте:

```bash
sudo chmod 600 /etc/netplan/*.yaml
sudo chown root:root /etc/netplan/*.yaml
sudo netplan try
```

Якщо з’єднання стабільне — підтвердіть у запиті **Enter** (інакше до таймаута відкотиться). Далі можна `sudo netplan apply`.

Попередження про занадто відкриті права на `/lib/netplan/00-network-manager-all.yaml` можна прибрати (не чіпає ваші файли в `/etc/netplan/`):

```bash
sudo chmod 600 /lib/netplan/00-network-manager-all.yaml
```

5. Перевірка:

```bash
iw dev wlan0 link
ip a show wlan0
ping -c 2 1.1.1.1
```

### 0.3) Швидке підключення через `nmcli` (разово або для тесту)

Коли NM уже активний, можна підключитися без ручного редагування YAML (профіль з’явиться в NM; після перезавантаження надійніше все одно зафіксувати в **Netplan**, як у **§0.2**):

```bash
nmcli device wifi list
sudo nmcli device wifi connect "ВАШ_SSID" password "Пароль"
nmcli device status
```

Щоб відключити зайвий профіль і підключити інший SSID:

```bash
nmcli connection show --active
sudo nmcli connection down "старий-профіль"
sudo nmcli device wifi connect "Новий_SSID" password "Пароль"
```

Після зміни **лише** Netplan-файлу старий профіль на кшталт `netplan-wlan0-aparts` інколи лишається у списку — його можна видалити: `sudo nmcli connection delete "netplan-wlan0-aparts"`, якщо він більше не потрібен.

### 0.4) Інтерактивно на Raspberry Pi OS (монітор + клавіатура)

Альтернатива без YAML:

```bash
sudo raspi-config
```

**System Options → Wireless LAN** — ввести SSID і пароль, за потреби `sudo reboot`.

### 0.5) Класичний лише `wpa_supplicant` (якщо NM не керує wlan0)

Має сенс лише на системах без NetworkManager для Wi‑Fi. Тоді правлять `/etc/wpa_supplicant/wpa_supplicant.conf`, перезапускають `wpa_supplicant@wlan0` або використовують `wpa_cli reconfigure` (див. також `man wpa_supplicant.conf`).

### Що варто знати

- **Статичний IP** — резервація DHCP на роутері за MAC `wlan0`, або додаткові поля в Netplan/NM (залежить від версії; для TV-дашборду часто достатньо стабільної DHCP-резервації).
- **Гостьові Wi‑Fi / captive portal** без браузера на сервері налаштувати важко; для залу краще звичайна WPA2/WPA3 мережа.
- Дашборд після появи IP: `http://<IP>:8000/` (або через nginx — **§8**).

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
# Обовʼязково для /admin та /dashboard/* (інакше 403). Далі вхід по HTTP Basic.
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_strong_password_here
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
- Дашборд (тільки перегляд): `http://<SERVER_IP>:8000/`
- Адмінка: `http://<SERVER_IP>:8000/admin`
- API логів: `POST /log` (з `X-API-Key`)

На дашборді WebSocket підключається як `ws://` або `wss://` залежно від того, чи сторінка відкрита по HTTP чи HTTPS (зручно за reverse proxy з TLS; див. **§8**).

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

## 8) Nginx (reverse proxy)

**Навіщо:** слухати стандартний порт **80** (і за потреби **443**), щоб у браузері не вказувати `:8000`, і коректно проксувати **WebSocket** (`/ws`) до uvicorn на `127.0.0.1:8000`.

### Встановлення

```bash
sudo apt update
sudo apt install -y nginx
```

### Конфігурація сайту

1. Створіть файл, наприклад `/etc/nginx/sites-available/smart-fizruk`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream smartfizruk_app {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location /ws {
        proxy_pass http://smartfizruk_app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    location / {
        proxy_pass http://smartfizruk_app;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`default_server` і `server_name _;` зручні для доступу **лише по локальному IP** (наприклад `http://192.168.0.213/`). Якщо є домен — замініть на `server_name example.com;` і приберіть `default_server`, якщо на цьому ж порту вже є інші сайти.

2. Увімкніть сайт і вимкніть дефолтний хост (якщо заважає):

```bash
sudo ln -sf /etc/nginx/sites-available/smart-fizruk /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

3. Перевірка з Маліни: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1/` → очікується **200** (при запущеному `ant_server` на 8000).

### Фаєрвол

```bash
sudo ufw allow 'Nginx HTTP'
# або для HTTPS після certbot:
sudo ufw allow 'Nginx Full'
```

### HTTPS і домен (опційно)

Якщо з інтернету відкривається порт 80 на вашій адресі:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com
```

Дашборд сам обере `wss://`, якщо сторінка відкрита по `https://`.

---

## 9) WireGuard (VPN)

**Навіщо:** окремий зашифрований канал до Маліни (другий IP у виводі `hostname -I`, наприклад `10.x.x.x`), доступ до внутрішніх сервісів без відкриття портів у провайдера або для зв’язку «офіс ↔ зал».

Нижче — типовий сценарій: **клієнт** WireGuard на Raspberry Pi з Debian/Raspberry Pi OS. Параметри тунелю (`PrivateKey`, `PublicKey` піра, `Endpoint`, `AllowedIPs`) видає адміністратор **сервера** WireGuard або хмарний провайдер.

### Встановлення

```bash
sudo apt update
sudo apt install -y wireguard wireguard-tools
```

### Ключі (на клієнті)

```bash
umask 077
wg genkey | tee ~/wg-private.key | wg pubkey > ~/wg-public.key
```

Вміст `~/wg-public.key` передайте тому, хто налаштовує сервер; у конфіг підставте вміст `~/wg-private.key` у `PrivateKey`.

### Приклад `/etc/wireguard/wg0.conf` (клієнт)

Значення `Address`, `PrivateKey`, `PublicKey` (пір), `Endpoint`, `AllowedIPs` мають збігатися з налаштуваннями на стороні сервера.

```ini
[Interface]
PrivateKey = <CLIENT_PRIVATE_KEY>
Address = 10.10.0.69/32

[Peer]
PublicKey = <SERVER_PUBLIC_KEY>
Endpoint = vpn.example.com:51820
AllowedIPs = 10.10.0.0/24
PersistentKeepalive = 25
```

- **`AllowedIPs`** — які мережі йдуть у тунель (наприклад лише підмережа VPN або `0.0.0.0/0` для повного тунелювання — залежить від політики).
- **`PersistentKeepalive`** — бажано за NAT, щоб сервер міг ініціювати відповідь.

Якщо в `[Interface]` додано **`DNS = ...`**, а `wg-quick` падає з помилкою на кшталт `resolvconf: command not found`, або встановіть пакет `openresolv` / `resolvconf`, або **приберіть рядок `DNS =`** з конфігу, якщо DNS через тунель не потрібен.

### Запуск і автозапуск

```bash
sudo cp /path/to/wg0.conf /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

Перевірка:

```bash
sudo wg show
ping -c 2 10.10.0.1
```

У полі `latest handshake` має бути недавній час — інакше перевірте `Endpoint`, ключі та фаєрвол на сервері.

### Зв’язок з цим проєктом

Після підняття тунелю дашборд можна відкривати по **VPN-IP** Маліни (якщо uvicorn слухає `0.0.0.0`), наприклад `http://10.10.0.69:8000/` або через nginx на 80 — залежно від того, з якої мережі приходить запит і чи дозволено це в `AllowedIPs` / маршрутах.

---

## 10) Бекап БД

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

## 11) Тестові користувачі

Для seed 20+ користувачів:

```bash
cd ~/ant_server
python3 migration_seed_test_users.py
```

## 12) Корисні URL та API

**Сторінки (HTML):**

- `GET /` — дашборд (картки + WebSocket)
- `GET /admin` — панель керування (модалки оренди, трекерів, користувачів)

**API:**

- `POST /log` — прийом пульсу від listener
- `POST /users/register` — додати користувача
- `POST /rentals/start` — почати/продовжити оренду за сьогодні
- `POST /rentals/stop` — завершити оренду
- `GET /settings/search-new-trackers`
- `PUT /settings/search-new-trackers`
- `GET /dashboard/users`
- `GET /dashboard/users/full`
- `POST /dashboard/users`
- `PUT /dashboard/users/{user_id}`
- `GET /dashboard/trackers`
- `PUT /dashboard/trackers/{device_id}` — назва та `correction_factor`
- `GET /dashboard/rentals/status`
- `GET /dashboard/rentals/active-customer`
- `POST /dashboard/rentals/start`
- `POST /dashboard/rentals/stop`
- `GET /dashboard/settings/search-new-trackers`
- `POST /dashboard/settings/search-new-trackers/toggle`
- `GET /dashboard/history` — зведення **по дню** (трекер + користувач): час тренування та ккал з БД пульсу (інтервали &lt; 10 с, Keytel, скоригований HR, дані користувача); фільтри: `device_id`, `customer_id`, `filter_date`; сортування: `sort_by` ∈ `day`, `device_name`, `customer_fullname`, `training_seconds`, `calories`, `sort_dir`, `limit`, `offset`

## 13) Troubleshooting

- **Немає Wi‑Fi / немає IP на `wlan0`**: див. **§0** (`rfkill`, **Netplan** у `/etc/netplan/`, **NetworkManager** / `nmcli device status`; не плутати з «сирою» правкою лише `wpa_supplicant.conf`, якщо активний `netplan-wlan0-*`; перевірити `ip link` та `dmesg | grep -i wlan`).
- **Порожній дашборд**: перевірити, чи є активні оренди в `device_rentals`.
- **Не приймає `/log`**: перевірити `X-API-Key` і значення в `.env`.
- **Не видно live-оновлень**: перевірити WebSocket `/ws` (за nginx — чи проксується `/ws` з `Upgrade`), статус сервісу `ant_server.service`.
- **HTTPS за проксі, дашборд OFFLINE**: має використовуватись `wss://` (у шаблоні дашборду схема береться з `https:` сторінки).
- **Картка не зникає після stop**: переконатися, що оновлений `server.py` розгорнуто і сервіс перезапущено.
- **Пошук трекерів / оренда / користувачі**: керування лише на сторінці `/admin` та відповідних `/dashboard/*` endpoints.
- **nginx 502 Bad Gateway**: переконайтеся, що `ant_server` запущений і слухає `127.0.0.1:8000` (`ss -tlnp | grep 8000`).
- **WireGuard `wg-quick` падає через `resolvconf`**: див. **§9** (рядок `DNS =` або встановлення `openresolv`/`resolvconf`).
