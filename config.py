import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Flask ----
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "True") == "True"
PORT = int(os.getenv("PORT", "5000"))

# ---- Gemini (기획/대본/프롬프트 설계) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---- Typecast (TTS, 나레이션 오디오 소스) ----
TYPECAST_API_KEY = os.getenv("TYPECAST_API_KEY", "")
TYPECAST_API_URL = os.getenv("TYPECAST_API_URL", "https://typecast.ai/api/speak")
TYPECAST_ACTOR_ID = os.getenv("TYPECAST_ACTOR_ID", "")
TYPECAST_MODEL = os.getenv("TYPECAST_MODEL", "ssfm-v21")

# ---- Flux (T2I, 씬 이미지 소스) ----
FLUX_API_KEY = os.getenv("FLUX_API_KEY", "")
FLUX_API_URL = os.getenv("FLUX_API_URL", "https://api.bfl.ai/v1/flux-pro-1.1")

# ---- Kling (I2V, 씬 영상 소스) ----
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "")
KLING_API_BASE = os.getenv("KLING_API_BASE", "https://api.klingai.com")

# ---- 출력 ----
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---- 이미지/영상 소스 스펙 (9:16) ----
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1920
KLING_CLIP_DURATION = 8  # Kling 8초 팩 고정 길이
