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
