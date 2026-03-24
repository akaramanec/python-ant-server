import sqlite3
from config import DB_FILE

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        # Користувачі
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT, last_name TEXT, middle_name TEXT,
                age INTEGER, height INTEGER, weight INTEGER,
                sex TEXT DEFAULT 'male'
            )
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