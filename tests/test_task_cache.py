import time

from app.task_cache import TaskCache


def test_task_cache_replaces_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "history.db"
    cache = TaskCache(path, ttl_seconds=300)
    result = cache.replace(
        active_tasks=[
            {"id": "task-1", "title": "Paint the wall", "status": "InProgress"},
            {"id": "task-2", "title": "Buy milk", "status": "ToDo"},
        ],
        today_tasks=[{"id": "task-2", "title": "Buy milk", "status": "ToDo"}],
    )

    assert result["active"]["count"] == 2
    assert result["today"]["count"] == 1
    assert result["today"]["fresh"] is True

    restarted = TaskCache(path, ttl_seconds=300)
    assert [task["id"] for task in restarted.get("active")["tasks"]] == [
        "task-1",
        "task-2",
    ]
    assert restarted.get("today")["tasks"][0]["title"] == "Buy milk"


def test_task_cache_writes_through_membership_changes(tmp_path) -> None:
    cache = TaskCache(tmp_path / "history.db")
    cache.replace(
        active_tasks=[{"id": "task-1", "title": "Original"}],
        today_tasks=[],
    )
    cache.upsert(
        {"id": "task-1", "title": "Due today", "due": "2026-11-17"},
        active=True,
        today=True,
    )
    assert cache.get("active")["tasks"][0]["title"] == "Due today"
    assert cache.get("today")["count"] == 1

    cache.upsert(
        {"id": "task-1", "title": "Completed", "completed": True},
        active=False,
        today=False,
    )
    assert cache.get("active")["count"] == 0
    assert cache.get("today")["count"] == 0


def test_empty_snapshot_is_warm_and_invalidation_makes_it_stale(tmp_path) -> None:
    cache = TaskCache(tmp_path / "history.db")
    cache.replace(active_tasks=[], today_tasks=[])
    empty = cache.get("today")
    assert empty["warm"] is True
    assert empty["fresh"] is True
    assert empty["count"] == 0

    cache.invalidate()
    assert cache.get("today")["warm"] is False
    assert cache.get("today")["fresh"] is False


def test_cache_expires_after_ttl(tmp_path) -> None:
    cache = TaskCache(tmp_path / "history.db", ttl_seconds=30)
    cache.replace(active_tasks=[], today_tasks=[])
    cache._refreshed_at["active"] = time.time() - 31
    assert cache.get("active")["fresh"] is False


def test_remove_deletes_task_from_both_views(tmp_path) -> None:
    cache = TaskCache(tmp_path / "history.db")
    task = {"id": "task-1", "title": "Delete me"}
    cache.replace(active_tasks=[task], today_tasks=[task])
    cache.remove("task-1")
    assert cache.get("active")["tasks"] == []
    assert cache.get("today")["tasks"] == []
