import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Flask ----
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "True") == "True"
PORT = int(os.getenv("PORT", "5000"))

# ---- Gemini ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---- Typecast ----
TYPECAST_API_KEY = os.getenv("TYPECAST_API_KEY", "")
TYPECAST_API_URL = os.getenv("TYPECAST_API_URL", "https://typecast.ai/api/speak")
TYPECAST_ACTOR_ID = os.getenv("TYPECAST_ACTOR_ID", "")
TYPECAST_MODEL = os.getenv("TYPECAST_MODEL", "ssfm-v21")

# ---- Flux ----
FLUX_API_KEY = os.getenv("FLUX_API_KEY", "")
FLUX_API_URL = os.getenv("FLUX_API_URL", "https://api.bfl.ai/v1/flux-pro-1.1")

# ---- Kling ----
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "")
KLING_API_BASE = os.getenv("KLING_API_BASE", "https://api.klingai.com")

# ---- OpenAI Whisper ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")

# ---- MoviePy 리소스 ----
FONT_PATH = os.getenv("FONT_PATH", os.path.join(BASE_DIR, "fonts", "NanumGothicBold.ttf"))
BGM_PATH = os.getenv("BGM_PATH", os.path.join(BASE_DIR, "assets", "bgm", "bgm.mp3"))
SFX_WHOOSH_PATH = os.getenv("SFX_WHOOSH_PATH", os.path.join(BASE_DIR, "assets", "sfx", "whoosh.mp3"))
SFX_IMPACT_PATH = os.getenv("SFX_IMPACT_PATH", os.path.join(BASE_DIR, "assets", "sfx", "impact.mp3"))

# ---- 출력 ----
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---- 영상 스펙 ----
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
KLING_CLIP_DURATION = 8  # Kling 8초 팩 고정 길이
