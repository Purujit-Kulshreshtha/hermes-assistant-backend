import base64
import json
import mimetypes
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
ALLOWED_TEXT_TYPES = {
    "text/plain", "text/markdown", "text/csv", "application/json",
    "application/xml", "text/xml",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_TEXT_TYPES | {"application/pdf"}


class Attachment(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int


def initialize_attachments(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size INTEGER NOT NULL,
                path TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_attachments (
                job_id TEXT NOT NULL,
                attachment_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (job_id, attachment_id)
            )
            """
        )


def save_attachment(
    db_path: Path, storage: Path, name: str, mime_type: str, content: bytes,
    max_bytes: int,
) -> Attachment:
    initialize_attachments(db_path)
    name = Path(name).name.strip()[:240]
    mime_type = mime_type.split(";", 1)[0].strip().lower()
    if not name or not content:
        raise ValueError("Attachment name and content are required")
    if len(content) > max_bytes:
        raise OverflowError(f"Attachment exceeds {max_bytes // (1024 * 1024)} MiB")
    if mime_type not in ALLOWED_TYPES:
        guessed = mimetypes.guess_type(name)[0]
        if guessed not in ALLOWED_TYPES:
            raise ValueError("Unsupported attachment type")
        mime_type = guessed
    attachment_id = uuid.uuid4().hex
    storage.mkdir(parents=True, exist_ok=True)
    destination = storage / attachment_id
    destination.write_bytes(content)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO attachments (id, name, mime_type, size, path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (attachment_id, name, mime_type, len(content), str(destination), time.time()),
        )
    return Attachment(id=attachment_id, name=name, mime_type=mime_type, size=len(content))


def attach_to_job(db_path: Path, job_id: str, attachment_ids: list[str]) -> None:
    if len(attachment_ids) > 5:
        raise ValueError("A message can contain at most five attachments")
    with sqlite3.connect(db_path) as connection:
        for position, attachment_id in enumerate(attachment_ids):
            if not connection.execute(
                "SELECT 1 FROM attachments WHERE id = ?", (attachment_id,)
            ).fetchone():
                raise KeyError(f"Attachment {attachment_id} not found")
            connection.execute(
                "INSERT INTO job_attachments (job_id, attachment_id, position) VALUES (?, ?, ?)",
                (job_id, attachment_id, position),
            )


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF support is not installed") from exc
    return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def hermes_attachment_parts(db_path: Path, job_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT a.name, a.mime_type, a.path
            FROM job_attachments j JOIN attachments a ON a.id = j.attachment_id
            WHERE j.job_id = ? ORDER BY j.position
            """,
            (job_id,),
        ).fetchall()
    parts: list[dict[str, Any]] = []
    for name, mime_type, raw_path in rows:
        path = Path(raw_path)
        if mime_type in ALLOWED_IMAGE_TYPES:
            encoded = base64.b64encode(path.read_bytes()).decode()
            parts.append({"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"})
            continue
        if mime_type == "application/pdf":
            text = _extract_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            if mime_type == "application/json":
                try:
                    text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
        text = text.strip()[:200_000]
        if not text:
            text = "[No extractable text]"
        parts.append({
            "type": "input_text",
            "text": f"\n--- Attached file: {name} ({mime_type}) ---\n{text}\n--- End attachment ---",
        })
    return parts


def delete_job_attachments(db_path: Path, job_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT a.id, a.path FROM job_attachments j
            JOIN attachments a ON a.id = j.attachment_id WHERE j.job_id = ?
            """,
            (job_id,),
        ).fetchall()
        connection.execute("DELETE FROM job_attachments WHERE job_id = ?", (job_id,))
        for attachment_id, raw_path in rows:
            connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            Path(raw_path).unlink(missing_ok=True)


def cleanup_attachments(db_path: Path, max_age_seconds: int = 86400) -> None:
    cutoff = time.time() - max_age_seconds
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, path FROM attachments
            WHERE created_at < ? AND id NOT IN (SELECT attachment_id FROM job_attachments)
            """,
            (cutoff,),
        ).fetchall()
        for attachment_id, raw_path in rows:
            connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            Path(raw_path).unlink(missing_ok=True)
