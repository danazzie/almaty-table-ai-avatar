import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

FAL_KEY = os.getenv("FAL_KEY") or os.getenv("FALAI_API_KEY", "")
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

MINIMAX_VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "").strip()
if not MINIMAX_VOICE_ID:
    voice_id_file = ROOT / "voice_id.txt"
    if voice_id_file.exists():
        MINIMAX_VOICE_ID = voice_id_file.read_text(encoding="utf-8").strip()

ENABLE_TTS = os.getenv("ENABLE_TTS", "false").lower() == "true"
ENABLE_AVATAR = os.getenv("ENABLE_AVATAR", "false").lower() == "true"

AVATAR_PHOTO_URL = os.getenv("AVATAR_PHOTO_URL", "")
VOICE_SAMPLE_URL = os.getenv("VOICE_SAMPLE_URL", "")

PHOTO_PATH = ROOT / "avatar" / "my_photo.jpg"
VOICE_SAMPLE_PATH = ROOT / "voice" / "my_voice_sample.wav"
CACHE_DIR = ROOT / ".cache"
OUTPUT_DIR = ROOT / "outputs"

TWOGIS_SERVER = ROOT / "mcp_servers" / "twogis" / "server.py"
CHOCOLIFE_SERVER = ROOT / "mcp_servers" / "chocolife" / "server.py"

MAX_REPLY_CHARS = 450  # keep spoken answers ~15–30s
SESSION_HISTORY_LIMIT = 12
