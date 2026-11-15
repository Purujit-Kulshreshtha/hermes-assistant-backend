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
- `POST /voice/sessions` — starts a browser voice-note upload.
- `PUT /voice/sessions/{id}/chunks/{sequence}` — uploads an ordered audio chunk.
- `POST /voice/sessions/{id}/finalize` — joins, normalizes and transcribes the note.

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
- `REQUEST_TIMEOUT_SECONDS`: defaults to `120`.
- `HISTORY_DB_PATH`: persistent SQLite database location.
- `OPENTODO_WEBHOOK_SECRET`: signing secret shown when the OpenTodo webhook
  delivery channel is created.
- `HEX_BIN`: Linux Hex executable used for transcription.
- `FFMPEG_BIN`: FFmpeg executable used to normalize browser recordings.
- `VOICE_TEMP_DIR`: temporary chunk storage; audio is removed after transcription.
- `VOICE_MAX_BYTES`: maximum bytes in one voice note (50 MiB by default).

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

### Browser text-to-speech

The PWA runs Kokoro-82M in a Web Worker and caches the downloaded model in the
browser. It uses WebGPU with WASM fallback, speaks replies sentence by sentence,
and stops playback as soon as voice recording begins. Enable **Browser speech**
in Settings and use **Test voice** to download the model and verify playback.
The Kokoro JavaScript runtime is pinned and served from `web/vendor`; its
Apache-2.0 license is included beside it. The first load requires access to
jsDelivr for ONNX runtime files and Hugging Face for model weights; later use
comes from the browser cache. If neural TTS cannot load, Nancy falls back to
the device's system speech engine and shows the failure detail in Settings.

## OpenTodo reminder delivery

In OpenTodo, open **Settings → Notifications → Delivery channels**, add a
**Webhook**, and use `https://voice-api.builtforyou.live/webhooks/opentodo`.
Enable **Reminders**, **Routine notices**, and **Include task titles**. Put the signing secret shown by
OpenTodo in `OPENTODO_WEBHOOK_SECRET`, restart `hermes-control`, then use the
channel's **Send test** action. Reminder deliveries are verified, deduplicated,
shown in Nancy's PWA, and spoken by the Mac companion after a notification sound.
