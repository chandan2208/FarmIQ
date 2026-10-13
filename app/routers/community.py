from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Comment, Post, get_db

router = APIRouter(prefix="/api/community", tags=["community"])
TOPICS = {"question", "pest", "market", "success", "equipment", "weather"}


class CommentIn(BaseModel):
    author: str = Field("Anonymous", max_length=60)
    body: str = Field(..., min_length=2, max_length=2000)


def _ago(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = (datetime.now(timezone.utc) - dt).total_seconds()
    for unit, size in (("year", 31536000), ("month", 2592000), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = int(s // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def _post_out(p: Post, with_comments: bool = True) -> dict:
    out = {
        "id": p.id, "author": p.author, "title": p.title, "body": p.body, "topic": p.topic, "crop": p.crop, "region": p.region,
        "image": p.image_path, "upvotes": p.upvotes, "created_at": p.created_at.isoformat(), "ago": _ago(p.created_at),
        "comment_count": len(p.comments),
    }
    if with_comments:
        out["comments"] = [{"id": c.id, "author": c.author, "body": c.body, "ago": _ago(c.created_at)} for c in p.comments]
    return out


@router.get("/posts")
def list_posts(topic: str | None = Query(None), crop: str | None = Query(None), limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    q = db.query(Post)
    if topic:
        q = q.filter(Post.topic == topic)
    if crop:
        q = q.filter(Post.crop == crop)
    posts = q.order_by(Post.created_at.desc()).limit(limit).all()
    return {"posts": [_post_out(p, with_comments=False) for p in posts]}


@router.get("/posts/{post_id}")
def get_post(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Post not found")
    return _post_out(p)


@router.post("/posts", status_code=201)
async def create_post(
    title: str = Form(..., min_length=3, max_length=140),
    body: str = Form(..., min_length=3, max_length=5000),
    topic: str = Form("question"),
    author: str = Form("Anonymous", max_length=60),
    crop: str | None = Form(None),
    region: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    if topic not in TOPICS:
        raise HTTPException(422, f"topic must be one of {sorted(TOPICS)}")
    image_path = None
    if image and image.filename:
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(415, "Images must be JPEG, PNG or WebP")
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[image.content_type]
        name = f"{uuid4().hex}.{ext}"
        (settings.upload_dir / name).write_bytes(await image.read())
        image_path = f"/uploads/{name}"
    p = Post(author=author.strip() or "Anonymous", title=title.strip(), body=body.strip(), topic=topic, crop=crop or None, region=region or None, image_path=image_path)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _post_out(p)


@router.post("/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, payload: CommentIn, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Post not found")
    c = Comment(post_id=post_id, author=payload.author.strip() or "Anonymous", body=payload.body.strip())
    db.add(c)
    db.commit()
    db.refresh(p)
    return _post_out(p)


@router.post("/posts/{post_id}/upvote")
def upvote(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Post not found")
    p.upvotes += 1
    db.commit()
    return {"id": p.id, "upvotes": p.upvotes}
