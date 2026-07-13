import datetime

from loguru import logger

from config import FIRESTORE_PROJECT, SESSION_COLLECTION, SESSION_TTL_DAYS

# Base64 characters per blob part; keeps each part document safely under
# Firestore's 1 MiB limit.
BLOB_CHUNK_CHARS = 800_000


class SessionStore:
    """Persists story sessions to Firestore so they survive restarts and
    scale-to-zero. All methods are blocking — call them from a thread.

    Layout:
      {SESSION_COLLECTION}/{sid}            -> session state minus images
      {SESSION_COLLECTION}/{sid}/blobs/*    -> base64 images, chunked
    """

    def __init__(self):
        self._client = None
        self._saved_blobs: dict[str, set[str]] = {}
        self.last_error: str | None = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import firestore
            kwargs = {"project": FIRESTORE_PROJECT} if FIRESTORE_PROJECT else {}
            self._client = firestore.Client(**kwargs)
        return self._client

    @property
    def status(self) -> str:
        if self.last_error:
            return f"unavailable: {self.last_error}"
        return "ok" if self._client else "idle"

    def save(self, state: dict) -> bool:
        sid = state.get("session_id")
        try:
            blobs = state.pop("blobs", {}) or {}
            doc_ref = self.client.collection(SESSION_COLLECTION).document(sid)

            saved = self._saved_blobs.setdefault(sid, set())
            for key, blob in blobs.items():
                # Storyboard/anchor blobs never change once written; only
                # 'last' is rewritten every turn.
                if key in saved and key != "last":
                    continue
                data = blob.get("data") or ""
                parts = [
                    data[i:i + BLOB_CHUNK_CHARS]
                    for i in range(0, len(data), BLOB_CHUNK_CHARS)
                ] or [""]
                for part_index, part in enumerate(parts):
                    doc_ref.collection("blobs").document(f"{key}__p{part_index}").set({
                        "key": key,
                        "part": part_index,
                        "parts": len(parts),
                        "mime": blob.get("mime"),
                        "data": part,
                    })
                saved.add(key)

            state["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
            state["expires_at"] = state["updated_at"] + datetime.timedelta(days=SESSION_TTL_DAYS)
            doc_ref.set(state)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)[:300]
            logger.warning("Session persist failed for session_id={}: {}", sid, exc)
            return False

    def load(self, sid: str) -> dict | None:
        try:
            doc_ref = self.client.collection(SESSION_COLLECTION).document(sid)
            snap = doc_ref.get()
            if not snap.exists:
                return None

            state = snap.to_dict()
            grouped: dict[str, dict[int, dict]] = {}
            for part_doc in doc_ref.collection("blobs").stream():
                part = part_doc.to_dict()
                grouped.setdefault(part["key"], {})[part["part"]] = part

            blobs = {}
            for key, parts in grouped.items():
                first = parts.get(0)
                if not first:
                    continue
                count = first.get("parts", 1)
                data = "".join(
                    parts[i]["data"] for i in range(count) if i in parts
                )
                blobs[key] = {"data": data, "mime": first.get("mime")}

            state["blobs"] = blobs
            # Everything in the store is already written; skip re-uploading.
            self._saved_blobs[sid] = set(blobs.keys()) - {"last"}
            self.last_error = None
            logger.info("Rehydrated session_id={} from Firestore", sid)
            return state
        except Exception as exc:
            self.last_error = str(exc)[:300]
            logger.warning("Session load failed for session_id={}: {}", sid, exc)
            return None
