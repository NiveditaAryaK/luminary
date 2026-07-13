import base64

from google.cloud import texttospeech
from loguru import logger

from config import TTS_DEFAULT_VOICE, TTS_LANGUAGE_CODE, TTS_MAX_CHARS_PER_REQUEST


GENRE_PROSODY = {
    "fantasy": {"rate": "medium", "pitch": "+1st"},
    "sci-fi": {"rate": "medium", "pitch": "-1st"},
    "mystery": {"rate": "medium", "pitch": "-2st"},
    "horror": {"rate": "slow", "pitch": "-3st"},
    "romance": {"rate": "medium", "pitch": "+2st"},
    "adventure": {"rate": "medium", "pitch": "+1st"},
    "historical": {"rate": "medium", "pitch": "-1st"},
}


class NarrationService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        # Created lazily and retried per call: on Cloud Run the metadata
        # server can be unavailable during cold start, and a one-shot
        # constructor failure would disable TTS for the process lifetime.
        if self._client is None:
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    def list_voices(self, language_code: str = TTS_LANGUAGE_CODE) -> list[dict]:
        response = self.client.list_voices(language_code=language_code)
        voices = []
        for voice in response.voices:
            voices.append({
                "name": voice.name,
                "language_codes": list(voice.language_codes),
                "gender": texttospeech.SsmlVoiceGender(voice.ssml_gender).name,
            })
        return voices

    def synthesize(self, text: str, genre: str, voice_name: str | None = None, language_code: str | None = None) -> dict:
        selected_language = language_code or TTS_LANGUAGE_CODE
        selected_voice = voice_name or TTS_DEFAULT_VOICE
        trimmed_text = (text or "").strip()[:TTS_MAX_CHARS_PER_REQUEST]
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
        )
        voice = texttospeech.VoiceSelectionParams(
            language_code=selected_language,
            name=selected_voice,
        )
        ssml = self._build_ssml(trimmed_text, genre)
        synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
        response = self.client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        logger.info(
            "Synthesized narration with voice='{}' genre='{}' chars={}",
            selected_voice,
            genre,
            len(trimmed_text),
        )
        return {
            "audio_base64": base64.b64encode(response.audio_content).decode(),
            "characters_used": len(trimmed_text),
            "mime_type": "audio/mpeg",
            "voice_name": selected_voice,
            "language_code": selected_language,
        }

    def _build_ssml(self, text: str, genre: str) -> str:
        prosody = GENRE_PROSODY.get(genre.lower(), {"rate": "medium", "pitch": "default"})
        clean_text = (text or "").replace("&", "and").replace("<", "").replace(">", "")
        return (
            "<speak>"
            f"<prosody rate=\"{prosody['rate']}\" pitch=\"{prosody['pitch']}\">"
            f"{clean_text}"
            "</prosody>"
            "</speak>"
        )
