from pydantic import BaseModel


class CreateReq(BaseModel):
    genre: str
    premise: str


class RestoreReq(BaseModel):
    title: str
    genre: str
    premise: str
    history: list[dict]
    turns: int = 0


class NarrationReq(BaseModel):
    text: str
    genre: str = "fantasy"
    voice_name: str | None = None
    language_code: str | None = None
