import json
import sqlite3
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal


TaskView = Literal["active", "today"]
VIEWS: tuple[TaskView, ...] = ("active", "today")


def initialize_task_cache(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_cache_entries (
                view TEXT NOT NULL CHECK (view IN ('active', 'today')),
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (view, task_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_cache_meta (
                view TEXT PRIMARY KEY CHECK (view IN ('active', 'today')),
                refreshed_at REAL NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def _validated_task(task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(task, dict):
        raise ValueError("Each cached task must be an object")
    task_id = str(task.get("id") or "").strip()
    title = str(task.get("title") or task.get("name") or "").strip()
    if not task_id or not title:
        raise ValueError("Each cached task requires non-empty id and title")
    payload = deepcopy(task)
    payload["id"] = task_id
    payload["title"] = title
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode()) > 64 * 1024:
        raise ValueError(f"Cached task {task_id!r} exceeds 64 KiB")
    return task_id, payload


class TaskCache:
    """Small persistent cache whose hot path is entirely in memory."""

    def __init__(self, path: Path, ttl_seconds: int = 300) -> None:
        self.path = path
        self.ttl_seconds = max(30, min(ttl_seconds, 86400))
        self._lock = threading.RLock()
        self._tasks: dict[TaskView, dict[str, dict[str, Any]]] = {
            "active": {},
            "today": {},
        }
        self._refreshed_at: dict[TaskView, float] = {"active": 0, "today": 0}
        self._revision: dict[TaskView, int] = {"active": 0, "today": 0}
        initialize_task_cache(path)
        self._load()

    def _load(self) -> None:
        with self._lock, sqlite3.connect(self.path) as connection:
            for view, task_id, payload in connection.execute(
                "SELECT view, task_id, payload FROM task_cache_entries"
            ):
                self._tasks[view][task_id] = json.loads(payload)
            for view, refreshed_at, revision in connection.execute(
                "SELECT view, refreshed_at, revision FROM task_cache_meta"
            ):
                self._refreshed_at[view] = refreshed_at
                self._revision[view] = revision

    def get(self, view: TaskView) -> dict[str, Any]:
        if view not in VIEWS:
            raise ValueError("view must be active or today")
        with self._lock:
            refreshed_at = self._refreshed_at[view]
            age = max(0.0, time.time() - refreshed_at) if refreshed_at else None
            return {
                "view": view,
                "tasks": deepcopy(list(self._tasks[view].values())),
                "count": len(self._tasks[view]),
                "warm": bool(refreshed_at),
                "fresh": age is not None and age <= self.ttl_seconds,
                "age_seconds": round(age, 1) if age is not None else None,
                "ttl_seconds": self.ttl_seconds,
                "revision": self._revision[view],
            }

    def replace(
        self,
        active_tasks: list[dict[str, Any]],
        today_tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if len(active_tasks) > 500 or len(today_tasks) > 500:
            raise ValueError("A task snapshot cannot contain more than 500 tasks")
        validated: dict[TaskView, dict[str, dict[str, Any]]] = {
            "active": dict(_validated_task(task) for task in active_tasks),
            "today": dict(_validated_task(task) for task in today_tasks),
        }
        now = time.time()
        with self._lock, sqlite3.connect(self.path) as connection:
            for view in VIEWS:
                connection.execute("DELETE FROM task_cache_entries WHERE view = ?", (view,))
                connection.executemany(
                    "INSERT INTO task_cache_entries (view, task_id, payload) VALUES (?, ?, ?)",
                    [
                        (view, task_id, json.dumps(task, separators=(",", ":"), ensure_ascii=False))
                        for task_id, task in validated[view].items()
                    ],
                )
                revision = self._revision[view] + 1
                connection.execute(
                    """
                    INSERT INTO task_cache_meta (view, refreshed_at, revision)
                    VALUES (?, ?, ?)
                    ON CONFLICT(view) DO UPDATE SET
                        refreshed_at = excluded.refreshed_at,
                        revision = excluded.revision
                    """,
                    (view, now, revision),
                )
                self._tasks[view] = validated[view]
                self._refreshed_at[view] = now
                self._revision[view] = revision
        return self.status()

    def upsert(self, task: dict[str, Any], active: bool, today: bool) -> dict[str, Any]:
        task_id, payload = _validated_task(task)
        membership: dict[TaskView, bool] = {"active": active, "today": today}
        now = time.time()
        with self._lock, sqlite3.connect(self.path) as connection:
            for view in VIEWS:
                if membership[view]:
                    connection.execute(
                        """
                        INSERT INTO task_cache_entries (view, task_id, payload)
                        VALUES (?, ?, ?)
                        ON CONFLICT(view, task_id) DO UPDATE SET payload = excluded.payload
                        """,
                        (view, task_id, json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
                    )
                    self._tasks[view][task_id] = deepcopy(payload)
                else:
                    connection.execute(
                        "DELETE FROM task_cache_entries WHERE view = ? AND task_id = ?",
                        (view, task_id),
                    )
                    self._tasks[view].pop(task_id, None)
                revision = self._revision[view] + 1
                connection.execute(
                    """
                    INSERT INTO task_cache_meta (view, refreshed_at, revision)
                    VALUES (?, ?, ?)
                    ON CONFLICT(view) DO UPDATE SET
                        refreshed_at = excluded.refreshed_at,
                        revision = excluded.revision
                    """,
                    (view, now, revision),
                )
                self._refreshed_at[view] = now
                self._revision[view] = revision
        return {"task_id": task_id, "active": active, "today": today, **self.status()}

    def remove(self, task_id: str) -> dict[str, Any]:
        task_id = task_id.strip()
        if not task_id:
            raise ValueError("task_id cannot be empty")
        now = time.time()
        with self._lock, sqlite3.connect(self.path) as connection:
            for view in VIEWS:
                connection.execute(
                    "DELETE FROM task_cache_entries WHERE view = ? AND task_id = ?",
                    (view, task_id),
                )
                self._tasks[view].pop(task_id, None)
                revision = self._revision[view] + 1
                connection.execute(
                    """
                    INSERT INTO task_cache_meta (view, refreshed_at, revision)
                    VALUES (?, ?, ?)
                    ON CONFLICT(view) DO UPDATE SET
                        refreshed_at = excluded.refreshed_at,
                        revision = excluded.revision
                    """,
                    (view, now, revision),
                )
                self._refreshed_at[view] = now
                self._revision[view] = revision
        return {"removed_task_id": task_id, **self.status()}

    def invalidate(self) -> dict[str, Any]:
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE task_cache_meta SET refreshed_at = 0")
            for view in VIEWS:
                self._refreshed_at[view] = 0
        return self.status()

    def status(self) -> dict[str, Any]:
        return {view: self.get(view) | {"tasks": []} for view in VIEWS}
