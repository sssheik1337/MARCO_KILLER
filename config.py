import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = {int(x) for x in os.getenv("ADMINS", "").split(',') if x.strip().isdigit()}
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TZ = os.getenv("TZ", "Europe/Moscow")
DB_PATH = os.getenv("DB_PATH", "data/database.sqlite3")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", 20))
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "msk")
TG_PROXY_URL = os.getenv("TG_PROXY_URL", "")
