from dotenv import load_dotenv
import os
from typing import Optional, List

# Загрузка переменных окружения из .env файла
load_dotenv()

# Токен бота Telegram
TG_TOKEN: Optional[str] = os.environ.get("TG_TOKEN")
CHANEL_ID: Optional[str] = os.environ.get("CHANEL_ID")
PROXY_API_KEY: Optional[str] = os.environ.get("PROXY_API_KEY")
API_ID: Optional[int] = int(os.environ.get("API_ID"))
API_HASH: Optional[str] = os.environ.get("API_HASH")

# Множество ID администраторов бота
ADMIN_IDS: List[int] = [int(x) for x in os.environ.get("ADMIN_IDS", "").split()] if os.environ.get("ADMIN_IDS") else []
