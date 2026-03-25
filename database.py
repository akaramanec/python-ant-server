import sqlite3
from datetime import datetime
from config import DB_FILE

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        # Налаштування
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR(50) PRIMARY KEY,
            name VARCHAR(250) NOT NULL,
            value VARCHAR(50)
            );
        """)
        # Користувачі
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT, last_name TEXT, middle_name TEXT,
                age INTEGER, height INTEGER, weight INTEGER,
                sex TEXT DEFAULT 'male'
            )
        """)
        # Трекери
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
            device_id INTEGER PRIMARY KEY,
            name VARCHAR(250) NOT NULL,
            is_active BOOLEAN DEFAULT 1
            );
        """)
        conn.execute("""
            INSERT OR IGNORE INTO settings (key, name, value)
            VALUES ('search_new_trackers', 'Пошук нових трекерів', '0')
        """)
        conn.execute("""
            INSERT OR IGNORE INTO settings (key, name, value)
            VALUES ('tracking_timeout_sec', 'Таймаут відсутності сигналу (сек)', '3')
        """)
        # Оренда (виправив відступ тут)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS device_rentals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER, device_id INTEGER,
                start_at TEXT, finish_at TEXT,
                calories REAL DEFAULT 0.0,
                FOREIGN KEY (customer_id) REFERENCES users(id)
            )
        """)
        # Логи пульсу
        conn.execute("""
            CREATE TABLE IF NOT EXISTS heart_rates (
                device_id INTEGER, timestamp TEXT, hr INTEGER,
                PRIMARY KEY (device_id, timestamp)
            )
        """)

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_active_user(device_id):
    with get_db_connection() as conn:
        # Додав calories у вибірку, щоб сервер міг їх підхопити
        return conn.execute("""
            SELECT u.first_name, u.last_name, u.age, u.weight, u.sex, r.start_at, r.calories
            FROM device_rentals r JOIN users u ON r.customer_id = u.id
            WHERE r.device_id = ? AND r.finish_at IS NULL
        """, (device_id,)).fetchone()

def update_user(user_id: int, data: dict):
    # Фільтруємо лише ті поля, які не None
    fields = {k: v for k, v in data.items() if v is not None}
    if not fields:
        return False

    keys = [f"{k} = ?" for k in fields.keys()]
    values = list(fields.values())
    values.append(user_id)

    query = f"UPDATE users SET {', '.join(keys)} WHERE id = ?"

    with get_db_connection() as conn:
        cursor = conn.execute(query, values)
        return cursor.rowcount > 0

def delete_user_full(user_id: int):
    with get_db_connection() as conn:
        # 1. Видаляємо записи пульсу, пов'язані з орендами цього користувача
        conn.execute("""
            DELETE FROM heart_rates
            WHERE device_id IN (SELECT device_id FROM device_rentals WHERE customer_id = ?)
        """, (user_id,))

        # 2. Видаляємо всі записи оренд
        conn.execute("DELETE FROM device_rentals WHERE customer_id = ?", (user_id,))

        # 3. Видаляємо самого користувача
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        return cursor.rowcount > 0

def get_dashboard_data():
    with get_db_connection() as conn:
        query = """
            SELECT r.device_id, u.first_name, u.last_name, r.start_at, u.age, u.weight,
                   h.hr, h.timestamp as ts, r.calories
            FROM device_rentals r
            JOIN users u ON r.customer_id = u.id
            LEFT JOIN heart_rates h ON r.device_id = h.device_id
            WHERE r.finish_at IS NULL
              AND (h.timestamp = (SELECT MAX(timestamp) FROM heart_rates WHERE device_id = r.device_id) OR h.timestamp IS NULL)
            ORDER BY h.timestamp DESC
        """
        return conn.execute(query).fetchall()

def update_rental_calories(device_id, calories):
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE device_rentals
            SET calories = ?
            WHERE device_id = ? AND finish_at IS NULL
        """, (calories, device_id))

def is_search_new_trackers_enabled() -> bool:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'search_new_trackers'"
        ).fetchone()
        if not row:
            return False
        return str(row["value"]) == "1"

def set_search_new_trackers_enabled(enabled: bool):
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO settings (key, name, value)
            VALUES ('search_new_trackers', 'Пошук нових трекерів', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, ("1" if enabled else "0",))

def get_tracking_timeout_sec(default_value: int = 3) -> int:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'tracking_timeout_sec'"
        ).fetchone()
        if not row:
            return default_value
        try:
            value = int(row["value"])
            return value if value > 0 else default_value
        except (TypeError, ValueError):
            return default_value

def tracker_exists(device_id) -> bool:
    device_id = int(device_id)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM trackers WHERE device_id = ? LIMIT 1",
            (device_id,)
        ).fetchone()
        return row is not None

def add_tracker_if_missing(device_id, name: str = None):
    device_id = int(device_id)
    tracker_name = name if name is not None else str(device_id)
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO trackers (device_id, name, is_active)
            VALUES (?, ?, 1)
        """, (device_id, tracker_name))

def update_tracker_name(device_id: int, name: str) -> bool:
    device_id = int(device_id)
    if name is None:
        return False
    new_name = str(name).strip()
    if not new_name:
        return False

    with get_db_connection() as conn:
        cursor = conn.execute("""
            UPDATE trackers
            SET name = ?
            WHERE device_id = ?
        """, (new_name, device_id))
        return cursor.rowcount > 0

def get_users_for_rental():
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT id, first_name, last_name
            FROM users
            ORDER BY last_name, first_name
        """).fetchall()

def get_users_full():
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT id,
                   first_name, last_name, middle_name,
                   age, height, weight, sex
            FROM users
            ORDER BY last_name, first_name
        """).fetchall()

def get_trackers_for_rental():
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT device_id, name
            FROM trackers
            WHERE is_active = 1
            ORDER BY name
        """).fetchall()

def is_pair_rental_active(customer_id: int, device_id: int) -> bool:
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM device_rentals
            WHERE customer_id = ? AND device_id = ? AND finish_at IS NULL
            LIMIT 1
        """, (customer_id, device_id)).fetchone()
        return row is not None

def stop_pair_rental(customer_id: int, device_id: int) -> int:
    with get_db_connection() as conn:
        now_str = datetime.now().isoformat()
        cursor = conn.execute("""
            UPDATE device_rentals
            SET finish_at = ?
            WHERE customer_id = ? AND device_id = ? AND finish_at IS NULL
        """, (now_str, customer_id, device_id))
        return cursor.rowcount

def start_or_resume_rental(customer_id: int, device_id: int):
    now_str = datetime.now().isoformat()
    today_str = datetime.now().date().isoformat()

    with get_db_connection() as conn:
        # На одному трекері має бути лише одна активна оренда.
        conn.execute("""
            UPDATE device_rentals
            SET finish_at = ?
            WHERE device_id = ? AND finish_at IS NULL
        """, (now_str, device_id))

        today_rental = conn.execute("""
            SELECT id, finish_at, calories
            FROM device_rentals
            WHERE customer_id = ? AND device_id = ? AND date(start_at) = ?
            ORDER BY start_at DESC
            LIMIT 1
        """, (customer_id, device_id, today_str)).fetchone()

        if today_rental:
            if today_rental["finish_at"] is not None:
                conn.execute("""
                    UPDATE device_rentals
                    SET finish_at = NULL
                    WHERE id = ?
                """, (today_rental["id"],))
            return {
                "action": "resumed",
                "calories": float(today_rental["calories"] or 0.0)
            }

        conn.execute("""
            INSERT INTO device_rentals (customer_id, device_id, start_at, finish_at, calories)
            VALUES (?, ?, ?, NULL, 0.0)
        """, (customer_id, device_id, now_str))
        return {"action": "created", "calories": 0.0}