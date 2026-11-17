# Hermes Voice Control API

A small authenticated API between voice clients and the private Hermes `voice`
profile. Hermes and OpenTodo remain bound to localhost.

## Endpoints

- `GET /health` — process health check.
- `POST /command` — sends natural-language text to Hermes and returns only the
  assistant's final text.
- `GET /history?conversation=voice-main` — returns persistent chat history for
  all clients using that conversation.
- `POST /commands` — accepts work immediately with HTTP 202.
- `GET /commands/{id}` — reports queued, running, completed or failed state.
- `GET/PUT /settings` — shared wake-word, voice and acknowledgement settings.
- `POST /webhooks/opentodo` — receives signed OpenTodo reminder deliveries.
- `GET /notifications?after=<cursor>` — lets authenticated clients consume reminders.
- `POST/GET /knowledge` — saves or searches private notes, ideas, bookmarks,
  meetings and voice notes using local SQLite full-text search.
- `GET/PUT/DELETE /knowledge/{id}` — reads, replaces or archives one entry.
- `POST /voice/sessions` — starts a browser voice-note upload.
- `PUT /voice/sessions/{id}/chunks/{sequence}` — uploads an ordered audio chunk.
- `POST /voice/sessions/{id}/finalize` — joins, normalizes and transcribes the note.
- `POST /attachments` — uploads a message attachment using `X-Filename`; up to
  five returned attachment IDs can be supplied to `POST /commands`.
- `GET/PUT/DELETE /board` — reads, presents or clears the current visual board.
- `GET /board/events` — streams live board updates to authenticated PWA clients.

## Local development

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
set -a; source .env; set +a
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Test with:

```bash
curl http://127.0.0.1:8787/health

curl http://127.0.0.1:8787/command \
  -H "Authorization: Bearer $CONTROL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"List my OpenTodo boards","conversation":"voice-main"}'
```

Run tests:

```bash
pytest -q
```

## Environment

- `CONTROL_API_KEY`: key presented by Mac/Android clients.
- `HERMES_API_KEY`: `API_SERVER_KEY` from the Hermes `voice` profile.
- `HERMES_URL`: defaults to the profile-prefixed local endpoint.
- `HERMES_MODEL`: defaults to `voice`.
- `HERMES_SESSION_GENERATION`: versions the upstream Hermes session independently
  from Nancy's visible chat history. Increment it after tool-catalog changes.
- `REQUEST_TIMEOUT_SECONDS`: defaults to `120`.
- `HISTORY_DB_PATH`: persistent SQLite database location.
- `TASK_CACHE_TTL_SECONDS`: freshness window for cached active/today task
  snapshots (defaults to `300`).
- `OPENTODO_WEBHOOK_SECRET`: signing secret shown when the OpenTodo webhook
  delivery channel is created.
- `HEX_BIN`: Linux Hex executable used for transcription.
- `FFMPEG_BIN`: FFmpeg executable used to normalize browser recordings.
- `VOICE_TEMP_DIR`: temporary chunk storage; audio is removed after transcription.
- `VOICE_MAX_BYTES`: maximum bytes in one voice note (50 MiB by default).
- `ATTACHMENT_DIR`: temporary attachment storage.
- `ATTACHMENT_MAX_BYTES`: maximum size per file (10 MiB by default).

Never commit `.env`. The client-facing and Hermes keys must be different.

## Oracle VM deployment

Clone the repository into `/opt/hermes-control`, create its virtual environment,
install `requirements.txt`, and place the production `.env` in that directory.
Then install `deploy/hermes-control.service` as
`/etc/systemd/system/hermes-control.service` and enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-control
sudo systemctl status hermes-control
curl http://127.0.0.1:8787/health
```

Keep port `8787` closed in OCI. Caddy publishes the service over HTTPS on port
443, while ports `8642` (Hermes) and `8080` (OpenTodo) stay private.

The production service uses `/var/lib/hermes-control` as `HOME` so Hex can keep
its downloaded model and caches inside the service's writable state directory.
Install the Linux ARM64 Hex executable at `/usr/local/bin/hex`, then run one
manual transcription as the `ubuntu` user with `HOME=/var/lib/hermes-control`
before enabling browser voice notes.

## Clients

The native macOS companion and menu-bar wrapper are deprecated. Voice input is
moving to chunked browser recording with server-side transcription; their source
remains under `clients/macos` only for migration.

The initial push-to-talk client is in `clients/macos`. It uses Hex for local
speech-to-text and macOS `say` for text-to-speech. See its README for setup.

The installable PWA is served at the root URL. The always-on macOS companion is
in `clients/macos/companion`; it uses local voice-activity capture, Hex file
transcription and local Kokoro TTS, and reads its settings from the PWA.

Voice sessions begin with the wake word alone, remain active for follow-ups, and
close on configurable stop phrases. Response playback supports speech barge-in;
stop-speaking controls are handled locally instead of being sent to Hermes.

The PWA also includes a read-only visual board beside chat. On mobile, Chat and
Board are horizontal scroll-snap pages: swipe left for the board and right for
chat. Hermes controls the board through the bundled `nancy_mcp.board_server` and
the `skills/nancy-visual-board` presentation skill. The same MCP process keeps
active and today OpenTodo task snapshots in memory, with behavior defined by
`skills/nancy-opentodo-cache`. See
`docs/visual-board.md` for deployment and configuration.

Nancy's personal knowledge base is local to the same SQLite database. The
`nancy-personal-knowledge` skill saves information only after an explicit request
to remember it, supports full-text recall and can present results with the
read-only `knowledge_list` and `knowledge_detail` board components.

The composer accepts drag-and-drop or button-selected attachments. Images are
sent to Hermes as inline vision input; PDF, text, Markdown, CSV, JSON and XML
files are extracted locally and supplied as bounded text. Temporary uploads are
deleted after the job completes or fails.

### Streaming text-to-speech

Kokoro runs on Oracle and generates replies one sentence at a time.
`POST /tts/stream` returns length-prefixed WAV frames, allowing the PWA to begin
playback while later sentences are still being synthesized. Generated sentences
are cached under `TTS_CACHE_DIR` (beside the history database by default). The
header **Stop** control aborts the HTTP stream and immediately stops playback;
starting a voice note does the same. If server speech is unavailable, the PWA
falls back to the device's system voice.

The first synthesis downloads Kokoro's model. Install `espeak-ng` and the Python
requirements on Oracle, then restart `hermes-control`.

## OpenTodo reminder delivery

In OpenTodo, open **Settings → Notifications → Delivery channels**, add a
**Webhook**, and use `https://voice-api.builtforyou.live/webhooks/opentodo`.
Enable **Reminders**, **Routine notices**, and **Include task titles**. Put the signing secret shown by
OpenTodo in `OPENTODO_WEBHOOK_SECRET`, restart `hermes-control`, then use the
channel's **Send test** action. Reminder deliveries are verified, deduplicated,
shown in Nancy's PWA, and spoken by the Mac companion after a notification sound.
