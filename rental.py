import requests
import json
import os
import sys
import io
from dotenv import load_dotenv

# Налаштування кодування для Linux/SSH терміналів
if sys.platform != 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')

def safe_input(prompt):
    """Зчитує дані з термінала, обходячи помилки UnicodeDecodeError"""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        # Читаємо сирі байти та декодуємо з ігноруванням помилок
        line = sys.stdin.buffer.readline()
        return line.decode('utf-8', errors='ignore').strip()
    except Exception:
        # Фолбек на звичайний input, якщо щось пішло не так
        return input().strip()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Налаштування API
API_KEY = os.getenv("API_KEY", "my_secret_key_123")
HOST = os.getenv("SERVER_HOST", "127.0.0.1")
PORT = int(os.getenv("SERVER_PORT", 8000))
API_URL = f"http://{HOST}:{PORT}"
HEADERS = {"X-API-Key": API_KEY}

def register_user():
    print("\n--- Реєстрація нового користувача ---")
    try:
        first_name = safe_input("Ім'я: ")
        last_name = safe_input("Прізвище: ")
        middle_name = safe_input("По батькові (необов'язково): ") or None
        age = int(safe_input("Вік: "))
        height = int(safe_input("Зріст (см): "))
        weight = int(safe_input("Вага (кг): "))
        sex = safe_input("Стать (male/female): ").lower().strip()

        data = {
            "first_name": first_name,
            "last_name": last_name,
            "middle_name": middle_name,
            "age": age,
            "height": height,
            "weight": weight,
            "sex": sex
        }
        r = requests.post(f"{API_URL}/users/register", json=data, headers=HEADERS)
        print("Результат:", r.json())
    except ValueError:
        print("Помилка: Вік, зріст та вага мають бути числами!")

def edit_user_ui():
    print("\n--- Редагування даних користувача ---")
    try:
        u_id = int(safe_input("Введіть ID користувача: "))
        print("Залиште порожнім, якщо не хочете змінювати поле")

        data = {}
        weight = safe_input("Нова вага (кг): ")
        if weight: data["weight"] = int(weight)

        age = safe_input("Новий вік: ")
        if age: data["age"] = int(age)

        sex = safe_input("Стать (male/female): ")
        if sex: data["sex"] = sex.lower().strip()

        if data:
            r = requests.put(f"{API_URL}/users/{u_id}", json=data, headers=HEADERS)
            print("Результат:", r.json())
        else:
            print("Нічого не змінено.")
    except ValueError:
        print("Помилка: Вводьте коректні числа!")

def delete_user_ui():
    print("\n--- ПОВНЕ ВИДАЛЕННЯ КОРИСТУВАЧА ---")
    u_id = safe_input("Введіть ID користувача для видалення: ")
    print(f"Ви впевнені, що хочете видалити ID {u_id} та ВСЮ історію?")
    confirm = safe_input("Підтвердіть (y/n): ")

    if confirm.lower() == 'y':
        r = requests.delete(f"{API_URL}/users/{u_id}", headers=HEADERS)
        print("Результат:", r.json())
    else:
        print("Скасовано.")

def start_rental():
    print("\n--- Початок тренування (Прив'язка датчика) ---")
    try:
        c_id = int(safe_input("ID користувача з бази: "))
        d_id = int(safe_input("ID ANT+ датчика: "))
        data = {"customer_id": c_id, "device_id": d_id}
        r = requests.post(f"{API_URL}/rentals/start", json=data, headers=HEADERS)
        print("Результат:", r.json())
    except ValueError:
        print("Помилка: ID мають бути числами!")

def stop_rental():
    print("\n--- Завершення тренування (Звільнення датчика) ---")
    try:
        d_id = int(safe_input("Введіть ID датчика для зупинки: "))
        r = requests.post(f"{API_URL}/rentals/stop", params={"device_id": d_id}, headers=HEADERS)
        print("Результат:", r.json())
    except ValueError:
        print("Помилка: ID датчика має бути числом!")

def main():
    while True:
        print("\n--- СИСТЕМА КЕРУВАННЯ ANT+ ---")
        print("1. Реєстрація нового користувача")
        print("2. Почати оренду (старт тренування)")
        print("3. Завершити оренду (стоп)")
        print("4. Редагувати дані користувача (вага/вік)")
        print("5. Видалити користувача та всю історію")
        print("0. Вихід")

        choice = safe_input("\nОберіть дію: ")

        if choice == '1':
            register_user()
        elif choice == '2':
            start_rental()
        elif choice == '3':
            stop_rental()
        elif choice == '4':
            edit_user_ui()
        elif choice == '5':
            delete_user_ui()
        elif choice == '0':
            print("Вихід...")
            break
        else:
            print("Невірний вибір!")

if __name__ == "__main__":
    main()