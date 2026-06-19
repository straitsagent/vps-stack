import os

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_ID = os.environ.get("TELEGRAM_OWNER_ID", "")  # Owner's Telegram chat ID
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
DRAFTS_GROUP_ID = os.environ.get("DRAFTS_GROUP_ID", "")  # Telegram group chat ID (negative int as string)

WM_BASE_URL = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
WM_WORKSPACE = os.environ.get("WM_WORKSPACE", "admins")
WM_TOKEN = os.environ["WM_TOKEN"]

AGENT_DB_URL = os.environ["AGENT_DB_URL"]

DEEPSEEK_KEY = os.environ["DEEPSEEK_KEY"]
XAI_KEY = os.environ["XAI_KEY"]
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")
EXA_KEY = os.environ.get("EXA_KEY", "")
FRED_KEY = os.environ.get("FRED_KEY", "")

DEEPSEEK_MODEL = "deepseek-chat"
GROK_MODEL = "grok-4"

# Tool latency classes
FAST = "fast"
ASYNC_NOTIFY = "async_notify"
FIRE = "fire"
GATED_WRITE = "gated_write"
MULTI_STEP = "multi_step"

ASYNC_POLL_INTERVAL = 5  # seconds
CONFIRMATION_TTL = 300   # seconds (5 min)
HISTORY_TURNS = 10
