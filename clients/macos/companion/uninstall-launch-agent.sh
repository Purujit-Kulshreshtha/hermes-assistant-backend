#!/bin/zsh
set -eu
label="live.builtforyou.nancy-companion"
plist="$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$UID/$label" 2>/dev/null || true
rm -f "$plist"
echo "Nancy companion launch agent removed."
