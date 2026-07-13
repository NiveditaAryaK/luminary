import asyncio
import json
import re
import secrets
import uuid
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from loguru import logger

from config import (
    FALLBACK_MODEL,
    YT_CLIENT_ID,
    YT_CLIENT_SECRET,
    YT_REDIRECT_URI,
    YT_TOKEN_COLLECTION,
)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024


class YouTubeError(RuntimeError):
    """Base class for publish failures surfaced to the API."""


class YouTubeNotConfiguredError(YouTubeError):
    """OAuth client credentials are not set on the server."""


class YouTubeNotConnectedError(YouTubeError):
    """The user has not linked a YouTube account yet."""


class YouTubeBusyError(YouTubeError):
    """An upload for this session is already in progress."""


class YouTubeService:
    """Links YouTube accounts via OAuth and uploads rendered films.

    Tokens are stored per user id in Firestore (memory-only fallback when
    Firestore is unavailable). Uploads run in a worker thread with job
    status polled the same way as film renders.
    """

    def __init__(self, genai_client=None, session_store=None):
        self.genai_client = genai_client
        self.session_store = session_store
        self._tokens: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    def configured(self) -> bool:
        return bool(YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REDIRECT_URI)

    def _flow(self) -> Flow:
        if not self.configured():
            raise YouTubeNotConfiguredError(
                "YouTube publishing is not configured. Set YT_CLIENT_ID, "
                "YT_CLIENT_SECRET and YT_REDIRECT_URI on the server."
            )
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": YT_CLIENT_ID,
                    "client_secret": YT_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=SCOPES,
            redirect_uri=YT_REDIRECT_URI,
        )

    def auth_url(self, uid: str) -> str:
        flow = self._flow()
        state = f"{uid}~{secrets.token_urlsafe(12)}"
        url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
            include_granted_scopes="false",
        )
        return url

    def handle_callback(self, state: str, code: str) -> str:
        """Exchange the authorization code for tokens. Blocking."""
        uid = (state or "").split("~", 1)[0]
        if not uid:
            raise YouTubeError("Missing state in OAuth callback.")
        flow = self._flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        record = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": list(creds.scopes or SCOPES),
        }
        self._tokens[uid] = record
        self._persist_tokens(uid, record)
        logger.info("YouTube account linked for uid={}", uid)
        return uid

    def _persist_tokens(self, uid: str, record: dict):
        if not self.session_store:
            return
        try:
            self.session_store.client.collection(YT_TOKEN_COLLECTION).document(uid).set(record)
        except Exception as exc:
            logger.warning("YouTube token persist failed for uid={}: {}", uid, exc)

    def _token_record(self, uid: str) -> dict | None:
        record = self._tokens.get(uid)
        if record:
            return record
        if not self.session_store:
            return None
        try:
            snap = self.session_store.client.collection(YT_TOKEN_COLLECTION).document(uid).get()
            if snap.exists:
                record = snap.to_dict()
                self._tokens[uid] = record
                return record
        except Exception as exc:
            logger.warning("YouTube token load failed for uid={}: {}", uid, exc)
        return None

    def connected(self, uid: str) -> bool:
        record = self._token_record(uid)
        return bool(record and record.get("refresh_token"))

    def _credentials(self, uid: str) -> Credentials:
        record = self._token_record(uid)
        if not record or not record.get("refresh_token"):
            raise YouTubeNotConnectedError("Connect your YouTube account first.")
        creds = Credentials(
            token=record.get("token"),
            refresh_token=record.get("refresh_token"),
            token_uri=record.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=YT_CLIENT_ID,
            client_secret=YT_CLIENT_SECRET,
            scopes=record.get("scopes") or SCOPES,
        )
        # Access tokens are short-lived and the stored one has unknown age;
        # refreshing up front avoids a mid-upload 401.
        creds.refresh(GoogleAuthRequest())
        record["token"] = creds.token
        self._persist_tokens(uid, record)
        return creds

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _fallback_metadata(self, session) -> dict:
        return {
            "title": f"{session.title} — an AI cinematic story"[:95],
            "description": (
                f"{session.premise}\n\n"
                f"A {session.genre} story created live with Luminary, "
                "an AI cinematic storytelling agent."
            ),
            "tags": [session.genre, "AI story", "Luminary", "interactive fiction"],
        }

    async def generate_metadata(self, session) -> dict:
        fallback = self._fallback_metadata(session)
        if not self.genai_client:
            return fallback

        prose = "\n".join(
            part.get("text", "")
            for entry in session.history if entry.get("role") == "model"
            for part in entry.get("parts") or []
            if part.get("text") and part.get("text") != "[illustration]"
        )[:3000]
        prompt = (
            "Write YouTube metadata for a short AI-generated story film. "
            "Return strict JSON with keys: title (max 90 chars, evocative, no clickbait), "
            "description (2-4 sentences, then a line crediting 'Made with Luminary — AI cinematic stories'), "
            "tags (5-10 short strings).\n"
            f"Story title: {session.title}\nGenre: {session.genre}\n"
            f"Premise: {session.premise}\nStory excerpt:\n{prose}"
        )
        try:
            from google.genai import types
            response = await self.genai_client.aio.models.generate_content(
                model=FALLBACK_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=500,
                    response_mime_type="application/json",
                ),
            )
            text = getattr(response, "text", "") or ""
            cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
            payload = json.loads(cleaned)
            return {
                "title": (payload.get("title") or fallback["title"])[:95],
                "description": (payload.get("description") or fallback["description"])[:4800],
                "tags": [str(tag)[:60] for tag in (payload.get("tags") or fallback["tags"])][:12],
            }
        except Exception as exc:
            logger.warning("YouTube metadata generation failed, using fallback: {}", exc)
            return fallback

    # ------------------------------------------------------------------
    # Publish job
    # ------------------------------------------------------------------

    def get_job(self, sid: str) -> dict | None:
        return self.jobs.get(sid)

    def job_public(self, job: dict) -> dict:
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": round(job["progress"], 3),
            "url": job["url"],
            "title": job["title"],
            "error": job["error"],
        }

    def start_publish(self, sid: str, uid: str, video_path: str, metadata: dict) -> dict:
        if not self.configured():
            raise YouTubeNotConfiguredError(
                "YouTube publishing is not configured on the server."
            )
        if not self.connected(uid):
            raise YouTubeNotConnectedError("Connect your YouTube account first.")
        existing = self.jobs.get(sid)
        if existing and existing["status"] in {"queued", "uploading"}:
            raise YouTubeBusyError("This film is already being published.")
        if not Path(video_path).is_file():
            raise YouTubeError("The rendered film is missing — render it again first.")

        job = {
            "job_id": str(uuid.uuid4()),
            "status": "queued",
            "progress": 0.0,
            "url": None,
            "title": metadata["title"],
            "error": None,
        }
        self.jobs[sid] = job
        task = asyncio.create_task(
            asyncio.to_thread(self._upload, job, uid, video_path, metadata)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("YouTube upload queued for session_id={} uid={}", sid, uid)
        return self.job_public(job)

    def _upload(self, job: dict, uid: str, video_path: str, metadata: dict):
        try:
            job["status"] = "uploading"
            creds = self._credentials(uid)
            youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
            body = {
                "snippet": {
                    "title": metadata["title"][:100],
                    "description": metadata["description"][:4900],
                    "tags": metadata["tags"][:15],
                    "categoryId": "24",
                },
                # Unverified API projects can only upload private videos;
                # the UI copy states this so the demo stays honest.
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": False,
                },
            }
            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                chunksize=UPLOAD_CHUNK_BYTES,
                resumable=True,
            )
            request = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    job["progress"] = status.progress()
            job["url"] = f"https://youtu.be/{response['id']}"
            job["progress"] = 1.0
            job["status"] = "done"
            logger.info("YouTube upload complete: {}", job["url"])
        except Exception as exc:
            logger.exception("YouTube upload failed: {}", exc)
            job["status"] = "error"
            job["error"] = str(exc)[:400]
