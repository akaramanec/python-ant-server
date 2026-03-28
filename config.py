import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

API_KEY = os.getenv("API_KEY", "default_secure_key")
DB_FILE = os.path.join(BASE_DIR, os.getenv("DB_PATH", "heart_data.db"))
HOST = os.getenv("SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("SERVER_PORT", 8000))

# /admin та /dashboard/*: обидва значення обовʼязкові в .env. Інакше адмін-зона повертає 403.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_AUTH_ENABLED = bool(ADMIN_USERNAME and ADMIN_PASSWORD)