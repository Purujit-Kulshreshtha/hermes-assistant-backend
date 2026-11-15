# Hermes Voice Control API

A small authenticated API between voice clients and the private Hermes `voice`
profile. Hermes and OpenTodo remain bound to localhost.

## Endpoints

- `GET /health` — process health check.
- `POST /command` — sends natural-language text to Hermes and returns only the
  assistant's final text.

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

Keep port `8787` closed in OCI. A Cloudflare Tunnel will publish this service
later, while ports `8642` (Hermes) and `8080` (OpenTodo) stay private.
