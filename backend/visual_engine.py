



"""Visual continuity engine.

Keeps every generated illustration in one session visually connected:
a style bible is generated once from the opening scene, and each new image
receives the anchor (first) and latest illustrations as reference inputs so
characters, palette, and art direction stay consistent across beats.
"""

import base64

from google.genai import types
from loguru import logger

from config import FALLBACK_MODEL, IMAGE_MODEL
from models import StoryEvent, StorySession
from text_utils import strip_choice_markup


STYLE_BIBLE_PROMPT = (
    "You are the art director for an illustrated cinematic story. "
    "Write a compact STYLE BIBLE (under 120 words) that an illustrator will follow for every scene. "
    "Include: art style and medium, color palette, lighting mood, and a one-line visual description "
    "of each main character (appearance, clothing, defining features). "
    "Reply with only the style bible text.\n"
    "Title: {title}\nGenre: {genre}\nOpening scene:\n{context}"
)


class VisualEngine:
    def __init__(self, client):
        self.client = client

    async def ensure_style_bible(self, session: StorySession, context: str):
        context = strip_choice_markup(context)
        if session.style_bible or not context.strip():
            return
        try:
            response = await self.client.aio.models.generate_content(
                model=FALLBACK_MODEL,
                contents=[{
                    "role": "user",
                    "parts": [{"text": STYLE_BIBLE_PROMPT.format(
                        title=session.title,
                        genre=session.genre,
                        context=context[:1500],
                    )}],
                }],
                config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=400),
            )
            text = (getattr(response, "text", None) or "").strip()
            if text:
                session.style_bible = text[:1200]
                logger.info("Style bible locked for session_id={}", session.session_id)
        except Exception as exc:
            logger.warning("Style bible generation failed: {}", exc)

    def reference_parts(self, session: StorySession) -> list[dict]:
        """Previous illustrations as inline reference parts (anchor + latest)."""
        parts = []
        seen = set()
        for image, mime in ((session.anchor_image, session.anchor_mime), (session.last_image, session.last_image_mime)):
            if not image or image in seen:
                continue
            seen.add(image)
            parts.append({
                "inline_data": {
                    "data": base64.b64decode(image),
                    "mime_type": mime or "image/png",
                }
            })
        return parts

    def register_image(self, session: StorySession, image_b64: str, mime_type: str | None):
        if not session.anchor_image:
            session.anchor_image = image_b64
            session.anchor_mime = mime_type
        session.last_image = image_b64
        session.last_image_mime = mime_type

    def adopt_restored_images(self, session: StorySession):
        """Rebuild anchor/latest references from a restored storyboard."""
        illustrated = [beat for beat in session.storyboard if beat.image]
        if not illustrated:
            return
        first, last = illustrated[0], illustrated[-1]
        session.anchor_image = first.image
        session.anchor_mime = first.mime_type
        session.last_image = last.image
        session.last_image_mime = last.mime_type

    async def generate_scene(self, session: StorySession, scene_text: str) -> StoryEvent | None:
        # Reader choices are UI, not scene content — if they reach the image
        # prompt the model paints them into the illustration.
        scene_text = strip_choice_markup(scene_text)
        if not scene_text.strip():
            return None

        await self.ensure_style_bible(session, scene_text)

        references = self.reference_parts(session)
        prompt = (
            f"Illustrate the next scene of this {session.genre} story.\n"
            f"Story title: {session.title}\n"
        )
        if session.style_bible:
            prompt += f"Follow this style bible exactly:\n{session.style_bible}\n"
        if references:
            prompt += (
                "The attached images are earlier scenes from THIS story. "
                "Keep the same characters, faces, wardrobe, art style, palette, and lighting language — "
                "this must look like the next frame of the same film.\n"
            )
        prompt += (
            f"Scene to illustrate:\n{scene_text[:1200]}\n"
            "The image must be purely visual: no words, letters, numbers, captions, "
            "subtitles, watermarks, menus, or interface elements of any kind."
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=IMAGE_MODEL,
                contents=[{"role": "user", "parts": references + [{"text": prompt}]}],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for candidate in getattr(response, "candidates", None) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", None) or []:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data:
                        image_b64 = base64.b64encode(inline_data.data).decode()
                        self.register_image(session, image_b64, inline_data.mime_type)
                        return StoryEvent(type="image", content=image_b64, mime_type=inline_data.mime_type)
        except Exception as exc:
            logger.warning("Connected scene image generation failed: {}", exc)
        return None
