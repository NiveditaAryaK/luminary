import os

from dotenv import load_dotenv

load_dotenv()

TITLE_MODEL = os.getenv("GEMINI_TITLE_MODEL", "gemini-2.5-flash")
STORY_MODEL = os.getenv("GEMINI_STORY_MODEL", "gemini-2.5-flash-image")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", STORY_MODEL)
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "en-US")
TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "en-US-Standard-F")
TTS_MAX_CHARS_PER_REQUEST = int(os.getenv("TTS_MAX_CHARS_PER_REQUEST", "1800"))
NARRATION_BEAT_THRESHOLD = int(os.getenv("NARRATION_BEAT_THRESHOLD", "150"))
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT", "")
SESSION_COLLECTION = os.getenv("SESSION_COLLECTION", "story_sessions")
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "")
YT_REDIRECT_URI = os.getenv("YT_REDIRECT_URI", "")
YT_TOKEN_COLLECTION = os.getenv("YT_TOKEN_COLLECTION", "yt_tokens")
PORT = int(os.getenv("PORT", 8080))

SYSTEM_INSTRUCTION = """You are Luminary, a master cinematic storyteller.
Create immersive interactive stories with INTERLEAVED text and generated images.
Write in second person. Each beat: 2-3 paragraphs of vivid prose + a generated scene illustration.
End every beat with 3 choices prefixed with: CHOICE_A: CHOICE_B: CHOICE_C:
Keep character appearances consistent. Cinematic, dramatic lighting in all images."""
