# macOS voice client (deprecated)

> Deprecated: new voice-input and notification work lives in the web app. This
> client is retained temporarily for migration and should not be installed on
> new devices.

This push-to-talk client uses the installed Hex app for recording and local
transcription, sends the resulting text to the Hermes control API, and reads the
final response aloud with macOS `say`.

## Set up

From this directory:

```bash
chmod +x setup-keychain.sh voice_client.py
./setup-keychain.sh
```

Paste the client-facing `CONTROL_API_KEY` when prompted. It is stored in macOS
Keychain and is never written to the repository.

Hex must be installed at `/Applications/Hex.app`. On first use, macOS may ask
Hex for microphone and accessibility permissions.

## Run

```bash
./voice_client.py
```

Press Enter to start recording, speak, and press Enter again to stop. The
existing server-side chat history is shown first. New transcripts and Hermes
responses are printed and retained for every device; responses are also spoken.

Test the network path without recording or TTS:

```bash
./voice_client.py --text "List my OpenTodo boards" --no-speak
```

Useful options:

```bash
./voice_client.py --no-speak
./voice_client.py --conversation another-device
```

Environment overrides are available for `CONTROL_API_URL`, `CONTROL_API_KEY`,
`VOICE_CONVERSATION`, and `HEX_BIN`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
