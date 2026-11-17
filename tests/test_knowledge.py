from app.knowledge import (
    KnowledgeWrite,
    archive_knowledge,
    create_knowledge,
    get_knowledge,
    search_knowledge,
    update_knowledge,
)


def test_knowledge_full_text_lifecycle(tmp_path) -> None:
    path = tmp_path / "history.db"
    entry = create_knowledge(
        path,
        KnowledgeWrite(
            kind="idea",
            title="Kitchen layout",
            content="Keep the sink on the east wall beside the window.",
            tags=["Home", "renovation", "home"],
            related_task_ids=["task-1"],
        ),
    )

    assert entry.tags == ["home", "renovation"]
    assert search_knowledge(path, "east wall").items[0].id == entry.id
    assert search_knowledge(path, "missing").items == []

    updated = update_knowledge(
        path,
        entry.id,
        KnowledgeWrite(
            kind="note",
            title="Kitchen decision",
            content="Move the sink to the north wall.",
            tags=["home"],
        ),
    )
    assert updated.title == "Kitchen decision"
    assert search_knowledge(path, "east wall").items == []
    assert search_knowledge(path, "north wall").items[0].id == entry.id

    archived = archive_knowledge(path, entry.id)
    assert archived.archived is True
    assert search_knowledge(path, "north wall").items == []
    assert get_knowledge(path, entry.id).archived is True


def test_recent_knowledge_can_be_filtered_by_kind(tmp_path) -> None:
    path = tmp_path / "history.db"
    create_knowledge(
        path,
        KnowledgeWrite(title="A note", content="General information", kind="note"),
    )
    create_knowledge(
        path,
        KnowledgeWrite(
            title="Reference", content="Useful website", kind="bookmark",
            source_url="https://example.com/reference",
        ),
    )

    results = search_knowledge(path, kind="bookmark")
    assert results.total == 1
    assert str(results.items[0].source_url) == "https://example.com/reference"
