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
APP="$(dirname "$CONTENTS")"
RES="$CONTENTS/Resources"
SUPPORT="${HANDMOUSE_SUPPORT:-$HOME/Library/Application Support/HandMouse}"
LOGDIR="$HOME/Library/Logs"
LOG="$LOGDIR/HandMouse.log"
SETTINGS="$SUPPORT/settings.txt"
VENV="$SUPPORT/venv"
PY_VERSION=3.12   # newest Python that has hand-tracking wheels for both Apple Silicon and Intel
REPO=rdydygin/handmouse
UPDATE_ASSET=Hand-Mouse-app.zip
UPDATE_URL="${HANDMOUSE_UPDATE_URL:-https://api.github.com/repos/$REPO/releases/latest}"
UPDATES="$SUPPORT/update"
STAGED="$UPDATES/Hand Mouse.app"
STATUS="$UPDATES/status"          # update status shown in the Hand Mouse window
CHECK_NOW="$UPDATES/check-now"    # created by the app when you press U

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

plist_version() {  # version string of an app bundle, empty if unreadable
  /usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$1/Contents/Info.plist" 2>/dev/null
}

is_version() { case "$1" in ''|*[!0-9.]*|.*|*.|*..*) return 1 ;; esac; }

version_gt() {  # true if version $1 is newer than version $2
  is_version "$1" && is_version "$2" && [ "$1" != "$2" ] || return 1
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | tail -n 1)" = "$1" ]
}

CURRENT_VERSION=$(plist_version "$APP")
echo "Version ${CURRENT_VERSION:-unknown} at $APP"

OFF_REASON=""
auto_update_enabled() {  # sets OFF_REASON when it returns false
  OFF_REASON=""
  if [ -n "${HANDMOUSE_NO_UPDATE:-}" ]; then OFF_REASON="turned off"; return 1; fi
  if [ -z "$CURRENT_VERSION" ]; then OFF_REASON="unknown version"; return 1; fi
  if [ -f "$SETTINGS" ] && sed -e 's/#.*//' "$SETTINGS" | grep -q -- '--no-auto-update'; then
    OFF_REASON="turned off in settings"; return 1
  fi
  # Not while running from a read-only, translocated copy, or where we can't replace the app.
  case "$APP" in */AppTranslocation/*) OFF_REASON="move the app to Applications"; return 1 ;; esac
  if [ ! -w "$APP" ] || [ ! -w "$(dirname "$APP")" ]; then
    OFF_REASON="the app can't replace itself here"; return 1
  fi
}

# One line "<state>|<text>", read by hand_mouse.py. States: checking, current,
# downloading, ready, available, error, off.
set_status() {
  mkdir -p "$UPDATES"
  printf '%s|%s\n' "$1" "$2" > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"
}
status_state() { [ -f "$STATUS" ] && sed -n '1s/|.*//p' "$STATUS"; }

# ---- install an update downloaded on a previous run -----------------------
if [ -d "$STAGED" ]; then
  NEW_VERSION=$(plist_version "$STAGED")
  if ! auto_update_enabled; then
    echo "Update to ${NEW_VERSION:-?} is waiting, but auto-update is off or the app can't be replaced"
  elif version_gt "$NEW_VERSION" "$CURRENT_VERSION" && [ -x "$STAGED/Contents/MacOS/HandMouse" ]; then
    echo "Installing update $CURRENT_VERSION -> $NEW_VERSION"
    OLD="$UPDATES/previous.app"
    rm -rf "$OLD"
    # Move, don't overwrite: this script keeps reading from the old copy until the exec below.
    if mv "$APP" "$OLD" && mv "$STAGED" "$APP"; then
      touch "$APP"   # make Finder and the Dock pick up the new version
      export HANDMOUSE_UPDATED_TO="$NEW_VERSION"
      exec "$APP/Contents/MacOS/HandMouse"
    fi
    echo "Update failed; keeping version $CURRENT_VERSION"
    if [ ! -d "$APP" ] && [ -d "$OLD" ]; then mv "$OLD" "$APP"; fi
    rm -rf "$STAGED"
  else
    echo "Discarding staged update ${NEW_VERSION:-?} (not newer than $CURRENT_VERSION)"
    rm -rf "$STAGED"
  fi
fi
if [ -n "${HANDMOUSE_UPDATED_TO:-}" ]; then
  unset HANDMOUSE_UPDATED_TO
  rm -rf "$UPDATES/previous.app"
  set_status current "Updated to $CURRENT_VERSION"
  osascript -e "display notification \"Updated to version $CURRENT_VERSION.\" with title \"Hand Mouse\"" >/dev/null 2>&1 &
fi

# ---- check for a newer release (runs in the background, see the end) ------
# check_for_update [force]: without "force", at most once a day (once an hour
# after a failed check). "force" is a check you asked for by pressing U.
check_for_update() {
  local force="${1:-}" enabled=1 json latest url work
  auto_update_enabled || enabled=""
  if [ -z "$enabled" ] && [ -z "$force" ]; then
    case "$(status_state)" in off|available) ;; *) set_status off "Auto-update off ($OFF_REASON)" ;; esac
    return 0
  fi
  mkdir -p "$UPDATES"
  if [ -z "$force" ]; then
    local minutes=1440
    [ "$(status_state)" = error ] && minutes=60
    if [ -n "$(find "$UPDATES/.last-check" -mmin -$minutes 2>/dev/null)" ]; then return 0; fi
  fi

  set_status checking "Checking for updates..."
  touch "$UPDATES/.last-check"
  if ! json=$(curl -fsSL --max-time 30 -H "Accept: application/vnd.github+json" "$UPDATE_URL"); then
    echo "Update check: could not reach GitHub"
    set_status error "Update check failed: no connection to GitHub"; return 0
  fi
  set -- $(printf '%s' "$json" | "$VENV/bin/python" -c '
import json, sys
r = json.load(sys.stdin)
url = next((a["browser_download_url"] for a in r.get("assets", []) if a.get("name") == sys.argv[1]), "")
if url and not r.get("draft") and not r.get("prerelease"):
    print(r.get("tag_name", "").lstrip("vV"), url)
' "$UPDATE_ASSET" 2>/dev/null)
  latest="${1:-}"; url="${2:-}"
  if [ -z "$url" ] || ! is_version "$latest"; then
    echo "Update check: no usable release found"
    set_status error "Update check failed: no release found"; return 0
  fi
  if ! version_gt "$latest" "$CURRENT_VERSION"; then
    echo "Update check: up to date (latest release $latest)"
    set_status current "Up to date"; return 0
  fi
  if [ -z "$enabled" ]; then
    echo "Update check: version $latest is available, but auto-update is off ($OFF_REASON)"
    set_status available "Version $latest available (auto-update off: $OFF_REASON)"; return 0
  fi
  if [ "$(plist_version "$STAGED")" = "$latest" ]; then
    set_status ready "Version $latest ready: reopen Hand Mouse to install"; return 0
  fi

  echo "Update check: downloading version $latest"
  set_status downloading "Downloading version $latest..."
  work="$UPDATES/download"
  rm -rf "$work"; mkdir -p "$work"
  if ! curl -fsSL --retry 3 --max-time 600 -o "$work/update.zip" "$url" \
     || ! ditto -x -k "$work/update.zip" "$work/unpacked" \
     || [ ! -x "$work/unpacked/Hand Mouse.app/Contents/MacOS/HandMouse" ] \
     || [ "$(plist_version "$work/unpacked/Hand Mouse.app")" != "$latest" ]; then
    echo "Update check: download of $latest failed or was not a valid app"
    set_status error "Download of version $latest failed"
    rm -rf "$work"; return 0
  fi
  xattr -cr "$work/unpacked/Hand Mouse.app" 2>/dev/null
  rm -rf "$STAGED"
  if mv "$work/unpacked/Hand Mouse.app" "$STAGED"; then
    echo "Update check: version $latest will be installed on next launch"
    set_status ready "Version $latest ready: reopen Hand Mouse to install"
  else
    set_status error "Could not save version $latest"
  fi
  rm -rf "$work"
}

# Checks once at launch, then about once a day while Hand Mouse runs, and right
# away when you press U in its window. Ends when Hand Mouse quits.
update_loop() {
  while kill -0 "$1" 2>/dev/null; do
    if [ -f "$CHECK_NOW" ]; then
      rm -f "$CHECK_NOW"
      echo "Update check: requested"
      check_for_update force
    else
      check_for_update
    fi
    sleep 2
  done
}

# Tidy up the status left by the previous run.
rm -f "$CHECK_NOW"
case "$(status_state)" in
  checking|downloading) rm -f "$UPDATES/.last-check" ;;          # interrupted: check again now
  ready) [ -d "$STAGED" ] || set_status current "Up to date" ;;  # installed or discarded since
esac

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
# --scroll-speed 5000  faster scrolling when moving the hand (default 3500)
# --tilt-scroll-speed 2000  faster scrolling when tilting the hand (default 1200)
# --no-tilt            tilting the hand doesn't scroll or swipe, only moving it does
# --swipe-action browser   peace-sign flick = browser back/forward instead of switching desktops
# --swipe-action off       turn peace-sign swipes off
# --no-four-finger-swipe   turn off the four-finger flick (thumb tucked) that switches desktops
# --allow-back-of-hand    keep tracking the hand when its back faces the camera
# --camera 1           use another camera (e.g. if an iPhone took over as camera 0)
# --no-auto-update     don't download new versions of Hand Mouse automatically
EOF
fi
# --no-auto-update is for this launcher, not for hand_mouse.py.
ARGS=$(sed -e 's/#.*//' -e 's/--no-auto-update//g' "$SETTINGS" | tr '\n' ' ')

# ---- run ------------------------------------------------------------------
export HANDMOUSE_ICON="$RES/HandMouse.icns"
export HANDMOUSE_SETTINGS="$SETTINGS"
export HANDMOUSE_VERSION="${CURRENT_VERSION:-unknown}"
export HANDMOUSE_UPDATE_STATUS="$STATUS"
export HANDMOUSE_UPDATE_REQUEST="$CHECK_NOW"
# shellcheck disable=SC2086  # ARGS is intentionally split into words
"$VENV/bin/python" "$RES/hand_mouse.py" --app --model "$RES/hand_landmarker.task" $ARGS &
CHILD=$!
update_loop "$CHILD" &
trap 'kill "$CHILD" 2>/dev/null' TERM INT HUP
wait "$CHILD"
CODE=$?
echo "Exited with code $CODE"
case "$CODE" in
  0|3|129|130|143) exit 0 ;;   # normal quit, error already shown (3), or stopped by the system
  2) fail "Hand Mouse did not understand a line in its settings file. Open ~/Library/Application Support/HandMouse/settings.txt and check the options you turned on." ;;
  *) fail "Hand Mouse stopped unexpectedly. If this keeps happening, delete the folder ~/Library/Application Support/HandMouse and open Hand Mouse again to reinstall." ;;
esac
