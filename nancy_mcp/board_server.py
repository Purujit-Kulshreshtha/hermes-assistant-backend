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


mcp = FastMCP("Nancy Visual Board")
component_adapter = TypeAdapter(BoardComponent)


def database_path() -> Path:
    return Path(os.environ.get("HISTORY_DB_PATH", "data/history.db"))


def prepare_database() -> Path:
    path = database_path()
    initialize_board_storage(path)
    return path


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


if __name__ == "__main__":
    mcp.run()
