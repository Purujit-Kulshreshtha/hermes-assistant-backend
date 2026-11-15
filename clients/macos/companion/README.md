# Nancy macOS companion

The PWA owns chat and settings. This small local process provides the abilities a
background browser cannot: continuous Hex listening and high-quality local TTS.

It reads the wake word, voice, speed and acknowledgement phrases from the PWA's
server settings before each interaction. Changing the wake word in Settings takes
effect without retraining a model or restarting the companion.

## Install TTS

Requires Apple Silicon, Hex and Homebrew `uv`:

```bash
brew install uv
./install-kokoro.sh
```

The first run downloads Kokoro 82M. Later synthesis is local.

## Run

The API key must already be stored by `../setup-keychain.sh`.

```bash
./run-companion.sh
```

Say the configured wake word followed by the instruction, for example:

> Nancy, create a task to buy paint in Home Improvement.

You can also say “Nancy”, pause, and give the instruction as the next utterance.

For a transcription-only test without installing Kokoro:

```bash
python3 companion.py --print-only
```

This first companion runs in Terminal. Packaging it as a signed menu-bar app and
Launch Agent is the next hardening step after microphone behavior is validated.

## Start automatically at login

After validating it in Terminal:

```bash
./install-launch-agent.sh
tail -f ~/Library/Logs/Nancy/companion.log
```

Remove automatic startup with `./uninstall-launch-agent.sh`.
