#!/bin/zsh
set -eu

service="hermes-voice-control"
account="$USER"

read -rs "api_key?Paste CONTROL_API_KEY: "
echo

if [[ -z "$api_key" ]]; then
  echo "The key cannot be empty." >&2
  exit 1
fi

security add-generic-password \
  -U \
  -a "$account" \
  -s "$service" \
  -w "$api_key" >/dev/null

unset api_key
echo "Saved in macOS Keychain as '$service'."
