import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from app.board import (
    BoardComponent,
    BoardDocument,
    clear_board as clear_saved_board,
    initialize_board_storage,
    remove_board_component as remove_saved_component,
    save_board,
    update_board_component as update_saved_component,
)
from pydantic import TypeAdapter
from app.task_cache import TaskCache


mcp = FastMCP("Nancy Visual Board")
component_adapter = TypeAdapter(BoardComponent)
task_cache: TaskCache | None = None


def database_path() -> Path:
    return Path(os.environ.get("HISTORY_DB_PATH", "data/history.db"))


def prepare_database() -> Path:
    path = database_path()
    initialize_board_storage(path)
    return path


def cached_tasks() -> TaskCache:
    global task_cache
    if task_cache is None:
        ttl = int(os.environ.get("TASK_CACHE_TTL_SECONDS", "300"))
        task_cache = TaskCache(database_path(), ttl)
    return task_cache


@mcp.tool()
def show_board(
    title: str,
    components: list[dict[str, Any]],
    conversation: str = "voice-main",
    layout: Literal["grid", "columns", "spotlight"] = "grid",
) -> dict[str, Any]:
    """Replace Nancy's read-only visual board with validated UI components."""
    document = BoardDocument(
        conversation=conversation,
        title=title,
        layout=layout,
        components=[component_adapter.validate_python(item) for item in components],
    )
    return save_board(prepare_database(), document).model_dump(mode="json")


@mcp.tool()
def update_component(
    component: dict[str, Any], conversation: str = "voice-main",
) -> dict[str, Any]:
    """Add or replace one component on Nancy's current visual board."""
    validated = component_adapter.validate_python(component)
    return update_saved_component(
        prepare_database(), conversation, validated
    ).model_dump(mode="json")


@mcp.tool()
def remove_component(
    component_id: str, conversation: str = "voice-main",
) -> dict[str, Any]:
    """Remove one component from Nancy's current visual board."""
    return remove_saved_component(
        prepare_database(), conversation, component_id
    ).model_dump(mode="json")


@mcp.tool()
def clear_board(conversation: str = "voice-main") -> dict[str, Any]:
    """Clear Nancy's visual board without affecting chat history."""
    return clear_saved_board(
        prepare_database(), conversation
    ).model_dump(mode="json")


@mcp.tool()
def get_cached_tasks(view: Literal["active", "today"]) -> dict[str, Any]:
    """Return OpenTodo tasks from Nancy's local memory cache without a network call."""
    return cached_tasks().get(view)


@mcp.tool()
def replace_task_cache(
    active_tasks: list[dict[str, Any]], today_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace both task views after fetching authoritative data from OpenTodo."""
    return cached_tasks().replace(active_tasks, today_tasks)


@mcp.tool()
def update_cached_task(
    task: dict[str, Any], active: bool, today: bool,
) -> dict[str, Any]:
    """Write through one created or updated OpenTodo task into both cached views."""
    return cached_tasks().upsert(task, active, today)


@mcp.tool()
def remove_cached_task(task_id: str) -> dict[str, Any]:
    """Remove a deleted OpenTodo task from every cached view."""
    return cached_tasks().remove(task_id)


@mcp.tool()
def invalidate_task_cache() -> dict[str, Any]:
    """Mark task snapshots stale when a mutation result lacks enough data to patch them."""
    return cached_tasks().invalidate()


@mcp.tool()
def task_cache_status() -> dict[str, Any]:
    """Report task-cache counts, freshness, age and revisions without returning tasks."""
    return cached_tasks().status()


if __name__ == "__main__":
    mcp.run()
