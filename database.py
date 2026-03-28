import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

import utils
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
            correction_factor REAL DEFAULT 1.0,
            is_active BOOLEAN DEFAULT 1
            );
        """)
        # Для вже існуючих БД (де колонка ще не додана)
        try:
            conn.execute("ALTER TABLE trackers ADD COLUMN correction_factor REAL DEFAULT 1.0")
        except sqlite3.OperationalError:
            pass
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
                   CAST(ROUND(h.hr * COALESCE(t.correction_factor, 1.0), 0) AS INTEGER) as hr,
                   h.timestamp as ts, r.calories
            FROM device_rentals r
            JOIN users u ON r.customer_id = u.id
            LEFT JOIN heart_rates h ON r.device_id = h.device_id
            LEFT JOIN trackers t ON r.device_id = t.device_id
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

def _parse_ts(ts):
    if ts is None:
        return None
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # SQLite часто зберігає heart_rates як "YYYY-MM-DD HH:MM:SS" без T — для fromisoformat
    if len(s) >= 19 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    elif " " in s and "T" not in s[:11]:
        s = s.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _format_duration(seconds: float) -> str:
    sec = int(round(max(0.0, seconds)))
    return str(timedelta(seconds=sec)).split(".")[0]


def _aggregate_day_samples(rows_sorted):
    """
    rows_sorted: список записів одного дня / одного трекера / одного клієнта, за часом зростання.
    Ккал і час як при live-логу: інтервали між сусідніми записами з 0 < Δ < 10 с;
    для ккал — формула Keytel, HR з коефіцієнтом трекера (на кожному зразку), вік/вага/стать користувача.
    """
    if not rows_sorted:
        return 0.0, 0.0
    total_sec = 0.0
    total_kcal = 0.0
    prev_dt = None

    for s in rows_sorted:
        dt = _parse_ts(s["timestamp"])
        if dt is None:
            continue
        age = s["age"]
        weight = s["weight"]
        sex = s["sex"] or "male"
        cf = float(s["correction_factor"] or 1.0)
        if cf <= 0:
            cf = 1.0
        hr_raw = float(s["hr"] or 0)
        hr_corr = int(round(hr_raw * cf))
        if prev_dt is not None:
            delta = (dt - prev_dt).total_seconds()
            if 0 < delta < 10:
                total_sec += delta
                total_kcal += utils.calculate_calories(hr_corr, age, weight, sex, delta)
        prev_dt = dt

    return total_sec, round(total_kcal, 1)


def get_daily_training_history(
    device_id=None,
    customer_id=None,
    filter_date=None,
    sort_by="day",
    sort_dir="desc",
    limit=500,
    offset=0,
    raw_row_cap=100000,
):
    """
    Агрегати по календарному дню + трекер + клієнт: час тренування та ккал з БД heart_rates
    (інтервали між зразками, як у /log) з урахуванням correction_factor та показників користувача.
    """
    # Порівняння часу лише через julianday: у heart_rates часто "YYYY-MM-DD HH:MM:SS",
    # у rentals — ISO з "T"; текстове h.timestamp >= r.start_at дає хибний false (пробіл < 'T').
    where_clauses = []
    params = []

    if device_id is not None:
        where_clauses.append("h.device_id = ?")
        params.append(int(device_id))

    if customer_id is not None:
        where_clauses.append("r.customer_id = ?")
        params.append(int(customer_id))

    if filter_date:
        where_clauses.append("date(h.timestamp) = date(?)")
        params.append(filter_date)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            h.device_id AS device_id,
            h.timestamp AS timestamp,
            h.hr AS hr,
            r.customer_id AS customer_id,
            u.age AS age,
            u.weight AS weight,
            u.sex AS sex,
            t.name AS device_name,
            COALESCE(t.correction_factor, 1.0) AS correction_factor,
            TRIM(COALESCE(u.last_name, '') || ' ' || COALESCE(u.first_name, '')) AS customer_fullname
        FROM heart_rates h
        INNER JOIN trackers t ON t.device_id = h.device_id
        INNER JOIN device_rentals r ON r.id = (
            SELECT r2.id
            FROM device_rentals r2
            WHERE r2.device_id = h.device_id
              AND julianday(h.timestamp) >= julianday(r2.start_at)
              AND (
                  r2.finish_at IS NULL
                  OR julianday(h.timestamp) <= julianday(r2.finish_at)
              )
            ORDER BY julianday(r2.start_at) DESC
            LIMIT 1
        )
        INNER JOIN users u ON u.id = r.customer_id
        WHERE {where_sql}
        ORDER BY h.timestamp DESC
        LIMIT ?
    """
    params.append(min(int(raw_row_cap), 200000))

    with get_db_connection() as conn:
        raw = [dict(row) for row in conn.execute(query, params).fetchall()]
        raw.reverse()

    groups = defaultdict(list)
    for row in raw:
        dt = _parse_ts(row["timestamp"])
        if dt is None:
            continue
        day = dt.date().isoformat()
        key = (day, row["device_id"], row["customer_id"])
        groups[key].append(row)

    results = []
    for (day, _dev, _cust), samples in groups.items():
        samples.sort(key=lambda x: str(x["timestamp"]))
        sec, kcal = _aggregate_day_samples(samples)
        first = samples[0]
        results.append({
            "day": day,
            "device_name": first["device_name"],
            "customer_fullname": first["customer_fullname"],
            "training_seconds": round(sec, 2),
            "training_time": _format_duration(sec),
            "calories": kcal,
        })

    reverse = str(sort_dir).lower() == "desc"
    sort_keys = {
        "day": lambda r: r["day"],
        "device_name": lambda r: (r["device_name"] or "").lower(),
        "customer_fullname": lambda r: (r["customer_fullname"] or "").lower(),
        "training_seconds": lambda r: r["training_seconds"],
        "calories": lambda r: r["calories"],
    }
    key_fn = sort_keys.get(sort_by) or sort_keys["day"]
    results.sort(key=key_fn, reverse=reverse)

    off = max(0, int(offset))
    lim = min(int(limit), 2000)
    return results[off : off + lim]


def get_tracker_correction_factor(device_id: int) -> float:
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT correction_factor
            FROM trackers
            WHERE device_id = ?
            LIMIT 1
        """, (int(device_id),)).fetchone()
        if not row:
            return 1.0
        try:
            value = float(row["correction_factor"])
            return value if value > 0 else 1.0
        except (TypeError, ValueError):
            return 1.0

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
            SELECT device_id, name, correction_factor
            FROM trackers
            WHERE is_active = 1
            ORDER BY name
        """).fetchall()

def update_tracker_settings(device_id: int, name: str, correction_factor: float) -> bool:
    device_id = int(device_id)
    if name is None:
        return False
    new_name = str(name).strip()
    if not new_name:
        return False

    try:
        new_factor = float(correction_factor)
    except (TypeError, ValueError):
        return False
    if new_factor <= 0:
        return False

    with get_db_connection() as conn:
        cursor = conn.execute("""
            UPDATE trackers
            SET name = ?, correction_factor = ?
            WHERE device_id = ?
        """, (new_name, new_factor, device_id))
        return cursor.rowcount > 0

def is_pair_rental_active(customer_id: int, device_id: int) -> bool:
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM device_rentals
            WHERE customer_id = ? AND device_id = ? AND finish_at IS NULL
            LIMIT 1
        """, (customer_id, device_id)).fetchone()
        return row is not None

def get_active_customer_for_device(device_id: int):
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT customer_id, calories
            FROM device_rentals
            WHERE device_id = ? AND finish_at IS NULL
            ORDER BY start_at DESC
            LIMIT 1
        """, (int(device_id),)).fetchone()
        if not row:
            return None
        return {
            "customer_id": int(row["customer_id"]),
            "calories": float(row["calories"] or 0.0),
        }

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
        active = conn.execute("""
            SELECT customer_id, calories
            FROM device_rentals
            WHERE device_id = ? AND finish_at IS NULL
            ORDER BY start_at DESC
            LIMIT 1
        """, (int(device_id),)).fetchone()

        if active:
            active_customer_id = int(active["customer_id"])
            if active_customer_id != int(customer_id):
                raise ValueError(f"Device {device_id} is already rented by customer {active_customer_id}")

            # Той самий користувач уже орендує цей трекер — просто повертаємо поточні дані.
            return {"action": "already_active", "calories": float(active["calories"] or 0.0)}

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