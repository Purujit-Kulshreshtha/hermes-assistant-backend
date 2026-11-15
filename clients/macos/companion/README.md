# Nancy macOS companion

The PWA owns chat and settings. This small local process provides the abilities a
background browser cannot: continuous Hex listening and high-quality local TTS.

It reads the wake word, voice, speed and acknowledgement phrases from the PWA's
server settings before each interaction. Changing the wake word in Settings takes
effect without retraining a model or restarting the companion.

## Install TTS

Requires Apple Silicon, Hex, PortAudio and Homebrew `uv`:

```bash
brew install uv portaudio
./install-kokoro.sh
```

The first run downloads Kokoro 82M. Later synthesis is local.

The companion records speech locally with voice-activity detection, then sends
each completed utterance to `hex transcribe`. This is necessary because
`hex listen` does not emit its live transcript to other processes.

Enable Hex file transcription once before starting:

```bash
/Applications/Hex.app/Contents/MacOS/hex labs on transcribe-files
```

If quiet speech is not detected, lower the threshold before starting:

```bash
export NANCY_SPEECH_THRESHOLD=0.008
```

The default end-of-speech pause is 1.4 seconds. Change **Pause before sending**
in the PWA settings; the companion applies it before the next utterance.

## Run

The API key must already be stored by `../setup-keychain.sh`.

```bash
./run-companion.sh
```

Say the configured wake word by itself:

> Nancy

Nancy answers with a listening cue such as “Yes?” or “Go on.” Give the
instruction as the next utterance. The conversation remains active for follow-up
instructions without repeating the wake word. Say a configured stop phrase such
as “That'll be all” to return to wake-word mode.

While Nancy reads a response, speaking above the barge-in threshold stops audio
playback and treats the utterance as the next instruction. Headphones give the
most reliable interruption because speaker audio can leak into the microphone.
Adjust sensitivity when needed:

```bash
export NANCY_BARGE_IN_THRESHOLD=0.04
```

Voice controls are handled locally and never sent to Hermes:

- “Stop talking” interrupts speech but leaves the conversation active.
- “That'll be all” closes the conversation.
- Saying the wake word alone while active resets to standby.

If a Hermes command stalls, the companion abandons it after 150 seconds and
returns to active listening.

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
