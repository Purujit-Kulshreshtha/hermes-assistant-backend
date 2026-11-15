# Nancy menu-bar app (deprecated)

> Deprecated in favour of the cross-platform PWA. Kept temporarily so existing
> installations can be removed cleanly.

Native AppKit wrapper for the Nancy voice companion. It displays a waveform in
the macOS menu bar, starts and stops the Python listener, opens the PWA chat in a
native window, and launches automatically after login.

## Install

Stop any Terminal companion first, then run:

```bash
./build-install.sh
```

The app is installed in `~/Applications/Nancy.app`; no administrator password is
needed. The first launch may request microphone access. The status menu includes
Open Nancy, Restart Listener, Stop Listener, Open Logs and Quit Nancy.

Double-tap the Right Option key to activate Nancy without saying the wake word.
Use **Nancy → Keyboard Trigger** to switch to Left Option or disable it. macOS
will request Accessibility permission so the trigger works while other apps are
active. The same setting is available in the PWA and synchronizes to the Mac
companion automatically.

The floating orb is cyan while listening, purple while processing, and green
while Nancy is speaking. It disappears when the conversation closes.

The app is ad-hoc signed for personal local use. Re-run the installer after
moving this repository because the companion path is embedded at build time.

## Uninstall

```bash
./uninstall.sh
```
