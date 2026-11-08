#!/bin/bash
# Hand Mouse.app launcher (Contents/MacOS/HandMouse).
#
# First launch: installs a private copy of Python and the libraries Hand Mouse
# needs into ~/Library/Application Support/HandMouse (a few minutes, needs
# internet). Nothing outside that folder is touched. Later launches start at once.
#
# Written for the bash 3.2 that ships with macOS.
set -u

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
RES="$CONTENTS/Resources"
SUPPORT="${HANDMOUSE_SUPPORT:-$HOME/Library/Application Support/HandMouse}"
LOGDIR="$HOME/Library/Logs"
LOG="$LOGDIR/HandMouse.log"
SETTINGS="$SUPPORT/settings.txt"
VENV="$SUPPORT/venv"
PY_VERSION=3.12   # newest Python that has hand-tracking wheels for both Apple Silicon and Intel

mkdir -p "$SUPPORT" "$LOGDIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then mv -f "$LOG" "$LOG.old"; fi
exec >>"$LOG" 2>&1
echo "=== Hand Mouse launched $(date) ($(uname -m), macOS $(sw_vers -productVersion 2>/dev/null))"

fail() {
  echo "ERROR: $1"
  answer=$(osascript -e 'activate' -e "button returned of (display dialog \"$1\" with title \"Hand Mouse\" buttons {\"Show Log\", \"OK\"} default button \"OK\" with icon stop)" 2>/dev/null)
  if [ "$answer" = "Show Log" ]; then open -a Console "$LOG"; fi
  exit 1
}

# ---- one-time setup -------------------------------------------------------
export UV_PYTHON_INSTALL_DIR="$SUPPORT/python"
export UV_CACHE_DIR="$SUPPORT/cache"
UV="${HANDMOUSE_UV:-$SUPPORT/bin/uv}"
STAMP="$VENV/.ready-$(cksum < "$RES/requirements.txt" | awk '{print $1}')"

if [ ! -f "$STAMP" ]; then
  echo "Setting up in $SUPPORT"
  osascript -e 'activate' -e 'display dialog "Hand Mouse is getting ready for first use.\n\nThis takes 2 to 5 minutes and needs an internet connection. Hand Mouse will open by itself when it is ready." with title "Hand Mouse" buttons {"OK"} default button "OK" giving up after 30' >/dev/null 2>&1 &

  if [ ! -x "$UV" ]; then
    case "$(uname -m)" in arm64) TRIPLE=aarch64-apple-darwin ;; *) TRIPLE=x86_64-apple-darwin ;; esac
    mkdir -p "$SUPPORT/bin"
    curl -fsSL --retry 3 "https://github.com/astral-sh/uv/releases/latest/download/uv-$TRIPLE.tar.gz" \
      | tar -xzf - -C "$SUPPORT/bin" --strip-components 1 \
      || fail "Could not download the installer. Check your internet connection and open Hand Mouse again."
  fi
  rm -rf "$VENV"
  "$UV" venv --python "$PY_VERSION" --python-preference only-managed "$VENV" \
    || fail "Could not install Python. Check your internet connection and open Hand Mouse again."
  "$UV" pip install --python "$VENV/bin/python" -r "$RES/requirements.txt" \
    || fail "Could not install the hand-tracking libraries. Check your internet connection and open Hand Mouse again."
  rm -rf "$UV_CACHE_DIR"
  touch "$STAMP"
  echo "Setup complete"
fi

# ---- settings file (press S in the Hand Mouse window to edit) -------------
if [ ! -f "$SETTINGS" ]; then
  cat > "$SETTINGS" <<'EOF'
# Hand Mouse settings
# Remove the # at the start of a line to turn that option on, save this file,
# then quit Hand Mouse (press Q in its window) and open it again.

# --speed 0.5          slower cursor (default 0.65; try 0.9 for faster)
# --reach 0.35         less arm movement to cross the screen (default 0.45)
# --smoothing 1.5      steadier cursor, a little more lag (default 1.0)
# --absolute           point at the screen directly instead of trackpad-style movement
# --pinch-on 0.33      clicks trigger more easily (default 0.28; lower = fewer accidental clicks)
# --invert-scroll      reverse scroll direction
# --scroll-speed 5000  faster scrolling (default 3500)
# --swipe-action browser   peace-sign flick = browser back/forward instead of switching desktops
# --swipe-action off       turn swipes off
# --camera 1           use another camera (e.g. if an iPhone took over as camera 0)
EOF
fi
ARGS=$(sed -e 's/#.*//' "$SETTINGS" | tr '\n' ' ')

# ---- run ------------------------------------------------------------------
export HANDMOUSE_ICON="$RES/HandMouse.icns"
export HANDMOUSE_SETTINGS="$SETTINGS"
# shellcheck disable=SC2086  # ARGS is intentionally split into words
"$VENV/bin/python" "$RES/hand_mouse.py" --app --model "$RES/hand_landmarker.task" $ARGS &
CHILD=$!
trap 'kill "$CHILD" 2>/dev/null' TERM INT HUP
wait "$CHILD"
CODE=$?
echo "Exited with code $CODE"
case "$CODE" in
  0|3|129|130|143) exit 0 ;;   # normal quit, error already shown (3), or stopped by the system
  2) fail "Hand Mouse did not understand a line in its settings file. Open ~/Library/Application Support/HandMouse/settings.txt and check the options you turned on." ;;
  *) fail "Hand Mouse stopped unexpectedly. If this keeps happening, delete the folder ~/Library/Application Support/HandMouse and open Hand Mouse again to reinstall." ;;
esac
