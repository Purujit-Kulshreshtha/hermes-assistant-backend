import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


KnowledgeKind = Literal["note", "idea", "bookmark", "meeting", "voice_note"]


class KnowledgeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: KnowledgeKind = "note"
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=100_000)
    source_url: HttpUrl | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    related_task_ids: list[str] = Field(default_factory=list, max_length=50)


class KnowledgeEntry(KnowledgeWrite):
    id: str
    archived: bool = False
    created_at: str
    updated_at: str


class KnowledgeResults(BaseModel):
    items: list[KnowledgeEntry]
    total: int


def initialize_knowledge(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_url TEXT,
                tags TEXT NOT NULL,
                related_task_ids TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                id UNINDEXED, title, content, tags, tokenize='unicode61'
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_updated ON knowledge_entries(updated_at DESC)"
        )


def _clean_values(value: KnowledgeWrite) -> KnowledgeWrite:
    value.title = value.title.strip()
    value.content = value.content.strip()
    value.tags = list(dict.fromkeys(tag.strip().lower() for tag in value.tags if tag.strip()))
    value.related_task_ids = list(dict.fromkeys(
        task_id.strip() for task_id in value.related_task_ids if task_id.strip()
    ))
    if not value.title or not value.content:
        raise ValueError("Knowledge title and content cannot be blank")
    return value


def _row(row: sqlite3.Row) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=row["id"], kind=row["kind"], title=row["title"], content=row["content"],
        source_url=row["source_url"], tags=json.loads(row["tags"]),
        related_task_ids=json.loads(row["related_task_ids"]),
        archived=bool(row["archived"]), created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _index(connection: sqlite3.Connection, entry_id: str, value: KnowledgeWrite) -> None:
    connection.execute("DELETE FROM knowledge_fts WHERE id = ?", (entry_id,))
    connection.execute(
        "INSERT INTO knowledge_fts (id, title, content, tags) VALUES (?, ?, ?, ?)",
        (entry_id, value.title, value.content, " ".join(value.tags)),
    )


def create_knowledge(path: Path, value: KnowledgeWrite) -> KnowledgeEntry:
    initialize_knowledge(path)
    value = _clean_values(value)
    entry_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_entries
                (id, kind, title, content, source_url, tags, related_task_ids,
                 archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                entry_id, value.kind, value.title, value.content,
                str(value.source_url) if value.source_url else None,
                json.dumps(value.tags), json.dumps(value.related_task_ids), now, now,
            ),
        )
        _index(connection, entry_id, value)
    return get_knowledge(path, entry_id)


def get_knowledge(path: Path, entry_id: str) -> KnowledgeEntry:
    initialize_knowledge(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM knowledge_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    if not row:
        raise KeyError("Knowledge entry not found")
    return _row(row)


def update_knowledge(path: Path, entry_id: str, value: KnowledgeWrite) -> KnowledgeEntry:
    get_knowledge(path, entry_id)
    value = _clean_values(value)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE knowledge_entries SET kind = ?, title = ?, content = ?,
                source_url = ?, tags = ?, related_task_ids = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                value.kind, value.title, value.content,
                str(value.source_url) if value.source_url else None,
                json.dumps(value.tags), json.dumps(value.related_task_ids), now, entry_id,
            ),
        )
        _index(connection, entry_id, value)
    return get_knowledge(path, entry_id)


def archive_knowledge(path: Path, entry_id: str) -> KnowledgeEntry:
    get_knowledge(path, entry_id)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE knowledge_entries SET archived = 1, updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), entry_id),
        )
        connection.execute("DELETE FROM knowledge_fts WHERE id = ?", (entry_id,))
    return get_knowledge(path, entry_id)


def search_knowledge(
    path: Path, query: str = "", kind: KnowledgeKind | None = None, limit: int = 20,
) -> KnowledgeResults:
    initialize_knowledge(path)
    limit = max(1, min(limit, 100))
    terms = re.findall(r"\w+", query, flags=re.UNICODE)[:20]
    parameters: list[object] = []
    if terms:
        match = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        sql = """
            SELECT e.* FROM knowledge_fts f
            JOIN knowledge_entries e ON e.id = f.id
            WHERE knowledge_fts MATCH ? AND e.archived = 0
        """
        parameters.append(match)
    else:
        sql = "SELECT e.* FROM knowledge_entries e WHERE e.archived = 0"
    if kind:
        sql += " AND e.kind = ?"
        parameters.append(kind)
    sql += " ORDER BY e.updated_at DESC LIMIT ?"
    parameters.append(limit)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(sql, parameters).fetchall()
    items = [_row(row) for row in rows]
    return KnowledgeResults(items=items, total=len(items))
