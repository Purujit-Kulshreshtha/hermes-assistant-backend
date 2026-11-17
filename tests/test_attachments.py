import sqlite3

from app.attachments import (
    attach_to_job,
    delete_job_attachments,
    hermes_attachment_parts,
    initialize_attachments,
    save_attachment,
)


def test_text_and_image_attachments_are_prepared_and_deleted(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    storage = tmp_path / "attachments"
    initialize_attachments(db_path)
    text = save_attachment(
        db_path, storage, "notes.md", "text/markdown", b"# Decision\nUse teal.",
        1024 * 1024,
    )
    image = save_attachment(
        db_path, storage, "screen.png", "image/png", b"not-a-real-png",
        1024 * 1024,
    )
    attach_to_job(db_path, "job-1", [text.id, image.id])
    parts = hermes_attachment_parts(db_path, "job-1")
    assert parts[0]["type"] == "input_text"
    assert "Use teal" in parts[0]["text"]
    assert parts[1]["image_url"].startswith("data:image/png;base64,")

    delete_job_attachments(db_path, "job-1")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert list(storage.iterdir()) == []
