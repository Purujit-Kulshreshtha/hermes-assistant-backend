#!/bin/zsh
set -eu
label="live.builtforyou.nancy-menubar"
launchctl bootout "gui/$UID/$label" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$label.plist"
osascript -e 'tell application "Nancy" to quit' 2>/dev/null || true
rm -rf "$HOME/Applications/Nancy.app"
echo "Nancy menu-bar app removed. Logs and companion files were preserved."
