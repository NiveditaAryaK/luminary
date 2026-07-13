import re

CHOICE_MARKUP = re.compile(
    r"CHOICE_[A-C]\s*:\s*[\s\S]*?(?=CHOICE_[A-C]\s*:|$)", re.IGNORECASE
)


def strip_choice_markup(text: str) -> str:
    """Remove CHOICE_A/B/C blocks and [illustration] markers from beat text.

    Mirrors the frontend's stripChoiceMarkup so prompts fed to the image
    model, captions, and film narration never contain choice UI text.
    """
    cleaned = CHOICE_MARKUP.sub("", text or "")
    cleaned = re.sub(r"\[illustration\]", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()
