#!/bin/zsh
set -eu

root="${0:A:h}"
companion="${root:h}/companion"
build="$root/.build"
app="$HOME/Applications/Nancy.app"
label="live.builtforyou.nancy-menubar"
plist="$HOME/Library/LaunchAgents/$label.plist"

mkdir -p "$build/module-cache" "$app/Contents/MacOS" "$app/Contents/Resources" "$HOME/Library/LaunchAgents"

swiftc \
  -module-cache-path "$build/module-cache" \
  -parse-as-library \
  -framework AppKit \
  -framework WebKit \
  "$root/Sources/main.swift" \
  -o "$app/Contents/MacOS/Nancy"

cp "$root/Resources/Info.plist" "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NancyCompanionPath $companion" "$app/Contents/Info.plist"
codesign --force --deep --sign - "$app" >/dev/null

# The menu app owns the companion; remove the older direct companion agent.
launchctl bootout "gui/$UID/live.builtforyou.nancy-companion" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/live.builtforyou.nancy-companion.plist"

cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$app/Contents/MacOS/Nancy</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF

launchctl bootout "gui/$UID/$label" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$plist"
launchctl kickstart "gui/$UID/$label"
echo "Installed Nancy in $app"
