#!/bin/zsh
set -eu

root="${0:A:h}"
label="live.builtforyou.nancy-companion"
plist="$HOME/Library/LaunchAgents/$label.plist"
log_dir="$HOME/Library/Logs/Nancy"
mkdir -p "${plist:h}" "$log_dir"

cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$root/run-companion.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$log_dir/companion.log</string>
  <key>StandardErrorPath</key><string>$log_dir/companion-error.log</string>
</dict></plist>
EOF

launchctl bootout "gui/$UID/$label" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$plist"
echo "Nancy companion now starts at login."
echo "Logs: $log_dir"
