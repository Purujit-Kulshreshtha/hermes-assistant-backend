# Nancy menu-bar app

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

The app is ad-hoc signed for personal local use. Re-run the installer after
moving this repository because the companion path is embedded at build time.

## Uninstall

```bash
./uninstall.sh
```
