from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import advisor

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


class Turn(BaseModel):
    role: str
    text: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    history: list[Turn] = Field(default_factory=list)
    language: str = Field("en", max_length=5)


@router.post("/ask")
async def ask(req: AskRequest):
    async def gen():
        yield f"event: meta\ndata: {json.dumps({'mode': advisor.mode()})}\n\n"
        async for chunk in advisor.stream(req.question, req.context, [t.model_dump() for t in req.history], req.language):
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/mode")
def mode():
    return {"mode": advisor.mode()}
