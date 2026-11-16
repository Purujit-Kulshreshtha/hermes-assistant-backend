import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=8000)]
ComponentId = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$"),
]


class HeadingData(StrictModel):
    text: ShortText
    subtitle: str | None = Field(default=None, max_length=500)
    level: Literal[1, 2, 3] = 2


class RichTextData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    text: LongText


class MetricItem(StrictModel):
    label: ShortText
    value: ShortText
    detail: str | None = Field(default=None, max_length=300)


class MetricCardsData(StrictModel):
    items: list[MetricItem] = Field(min_length=1, max_length=8)


class ListItem(StrictModel):
    title: ShortText
    subtitle: str | None = Field(default=None, max_length=500)
    badge: str | None = Field(default=None, max_length=80)


class ListData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    items: list[ListItem] = Field(max_length=50)


class TaskItem(StrictModel):
    title: ShortText
    project: str | None = Field(default=None, max_length=120)
    due: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=80)


class TaskListData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    tasks: list[TaskItem] = Field(max_length=50)


class EmailItem(StrictModel):
    sender: ShortText
    subject: ShortText
    preview: str | None = Field(default=None, max_length=500)
    time: str | None = Field(default=None, max_length=100)
    unread: bool = False


class EmailListData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    messages: list[EmailItem] = Field(max_length=30)


class EmailDetailData(StrictModel):
    sender: ShortText
    recipients: list[ShortText] = Field(default_factory=list, max_length=30)
    subject: ShortText
    date: str | None = Field(default=None, max_length=120)
    body: LongText


class CalendarEvent(StrictModel):
    time: ShortText
    title: ShortText
    duration: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=240)


class CalendarAgendaData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    date: str | None = Field(default=None, max_length=120)
    events: list[CalendarEvent] = Field(max_length=40)


class EventDetailData(StrictModel):
    title: ShortText
    start: ShortText
    end: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=240)
    attendees: list[ShortText] = Field(default_factory=list, max_length=50)
    description: str | None = Field(default=None, max_length=4000)


class TimelineItem(StrictModel):
    time: ShortText
    title: ShortText
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=80)


class TimelineData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    items: list[TimelineItem] = Field(max_length=50)


class TableData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    columns: list[ShortText] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(max_length=100)


class KeyValueItem(StrictModel):
    label: ShortText
    value: str = Field(max_length=2000)


class KeyValueData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    items: list[KeyValueItem] = Field(max_length=40)


class ChartSeries(StrictModel):
    name: ShortText
    values: list[float] = Field(min_length=1, max_length=30)


class ChartData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    kind: Literal["bar", "line", "donut"] = "bar"
    labels: list[ShortText] = Field(min_length=1, max_length=30)
    series: list[ChartSeries] = Field(min_length=1, max_length=6)


class ImageData(StrictModel):
    src: HttpUrl
    alt: ShortText
    caption: str | None = Field(default=None, max_length=500)


class CalloutData(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    text: LongText
    tone: Literal["info", "success", "warning", "danger"] = "info"


class LoadingData(StrictModel):
    text: str = Field(default="Gathering information…", max_length=200)


class EmptyStateData(StrictModel):
    title: ShortText
    text: str | None = Field(default=None, max_length=1000)


class HeadingComponent(StrictModel):
    id: ComponentId
    type: Literal["heading"]
    data: HeadingData


class RichTextComponent(StrictModel):
    id: ComponentId
    type: Literal["rich_text"]
    data: RichTextData


class MetricCardsComponent(StrictModel):
    id: ComponentId
    type: Literal["metric_cards"]
    data: MetricCardsData


class ListComponent(StrictModel):
    id: ComponentId
    type: Literal["list"]
    data: ListData


class TaskListComponent(StrictModel):
    id: ComponentId
    type: Literal["task_list"]
    data: TaskListData


class EmailListComponent(StrictModel):
    id: ComponentId
    type: Literal["email_list"]
    data: EmailListData


class EmailDetailComponent(StrictModel):
    id: ComponentId
    type: Literal["email_detail"]
    data: EmailDetailData


class CalendarAgendaComponent(StrictModel):
    id: ComponentId
    type: Literal["calendar_agenda"]
    data: CalendarAgendaData


class EventDetailComponent(StrictModel):
    id: ComponentId
    type: Literal["event_detail"]
    data: EventDetailData


class TimelineComponent(StrictModel):
    id: ComponentId
    type: Literal["timeline"]
    data: TimelineData


class TableComponent(StrictModel):
    id: ComponentId
    type: Literal["table"]
    data: TableData


class KeyValueComponent(StrictModel):
    id: ComponentId
    type: Literal["key_value"]
    data: KeyValueData


class ChartComponent(StrictModel):
    id: ComponentId
    type: Literal["chart"]
    data: ChartData


class ImageComponent(StrictModel):
    id: ComponentId
    type: Literal["image"]
    data: ImageData


class CalloutComponent(StrictModel):
    id: ComponentId
    type: Literal["callout"]
    data: CalloutData


class LoadingComponent(StrictModel):
    id: ComponentId
    type: Literal["loading"]
    data: LoadingData


class EmptyStateComponent(StrictModel):
    id: ComponentId
    type: Literal["empty_state"]
    data: EmptyStateData


BoardComponent = Annotated[
    Union[
        HeadingComponent,
        RichTextComponent,
        MetricCardsComponent,
        ListComponent,
        TaskListComponent,
        EmailListComponent,
        EmailDetailComponent,
        CalendarAgendaComponent,
        EventDetailComponent,
        TimelineComponent,
        TableComponent,
        KeyValueComponent,
        ChartComponent,
        ImageComponent,
        CalloutComponent,
        LoadingComponent,
        EmptyStateComponent,
    ],
    Field(discriminator="type"),
]


class BoardDocument(StrictModel):
    version: Literal[1] = 1
    conversation: str = Field(default="voice-main", min_length=1, max_length=100)
    title: str = Field(default="Visual board", min_length=1, max_length=200)
    layout: Literal["grid", "columns", "spotlight"] = "grid"
    components: list[BoardComponent] = Field(default_factory=list, max_length=24)


class BoardState(BoardDocument):
    revision: int = Field(ge=1)
    updated_at: str


def initialize_board_storage(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS visual_boards (
                conversation TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                document TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def save_board(path: Path, document: BoardDocument) -> BoardState:
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT revision FROM visual_boards WHERE conversation = ?",
            (document.conversation,),
        ).fetchone()
        revision = (row[0] if row else 0) + 1
        connection.execute(
            """
            INSERT INTO visual_boards (conversation, revision, document, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation) DO UPDATE SET
                revision = excluded.revision,
                document = excluded.document,
                updated_at = excluded.updated_at
            """,
            (document.conversation, revision, document.model_dump_json(), now),
        )
    return BoardState(**document.model_dump(), revision=revision, updated_at=now)


def load_board(path: Path, conversation: str) -> BoardState | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT revision, document, updated_at
            FROM visual_boards WHERE conversation = ?
            """,
            (conversation,),
        ).fetchone()
    if not row:
        return None
    document = BoardDocument.model_validate_json(row[1])
    return BoardState(**document.model_dump(), revision=row[0], updated_at=row[2])


def update_board_component(
    path: Path, conversation: str, component: BoardComponent,
) -> BoardState:
    current = load_board(path, conversation)
    if current:
        components = list(current.components)
        title = current.title
        layout = current.layout
    else:
        components = []
        title = "Visual board"
        layout = "grid"
    for index, existing in enumerate(components):
        if existing.id == component.id:
            components[index] = component
            break
    else:
        components.append(component)
    return save_board(path, BoardDocument(
        conversation=conversation, title=title, layout=layout, components=components,
    ))


def remove_board_component(path: Path, conversation: str, component_id: str) -> BoardState:
    current = load_board(path, conversation)
    if not current:
        return save_board(path, BoardDocument(conversation=conversation))
    components = [item for item in current.components if item.id != component_id]
    return save_board(path, BoardDocument(
        conversation=conversation,
        title=current.title,
        layout=current.layout,
        components=components,
    ))


def clear_board(path: Path, conversation: str) -> BoardState:
    return save_board(path, BoardDocument(conversation=conversation))
