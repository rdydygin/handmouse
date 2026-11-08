#!/usr/bin/env bash
# Builds "dist/Hand Mouse.app" from the files in this folder.
# Re-run it after editing hand_mouse.py. Works on macOS and Linux.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/Hand Mouse.app"
MODEL=models/hand_landmarker.task
VERSION=1.6   # bump this, then push a tag "v<VERSION>" to publish a release

if [ ! -f "$MODEL" ]; then
  mkdir -p models
  echo "Downloading hand tracking model..."
  curl -fsSL -o "$MODEL.part" \
    https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
  mv "$MODEL.part" "$MODEL"
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/launcher.sh "$APP/Contents/MacOS/HandMouse"
chmod 755 "$APP/Contents/MacOS/HandMouse"
cp hand_mouse.py requirements.txt assets/HandMouse.icns "$MODEL" "$APP/Contents/Resources/"
printf 'APPL????' > "$APP/Contents/PkgInfo"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>                 <string>Hand Mouse</string>
  <key>CFBundleDisplayName</key>          <string>Hand Mouse</string>
  <key>CFBundleIdentifier</key>           <string>local.handmouse.app</string>
  <key>CFBundleExecutable</key>           <string>HandMouse</string>
  <key>CFBundleIconFile</key>             <string>HandMouse</string>
  <key>CFBundlePackageType</key>          <string>APPL</string>
  <key>CFBundleShortVersionString</key>   <string>$VERSION</string>
  <key>CFBundleVersion</key>              <string>$VERSION</string>
  <key>LSMinimumSystemVersion</key>       <string>11.0</string>
  <key>LSApplicationCategoryType</key>    <string>public.app-category.utilities</string>
  <!-- The launcher stays in the background; the tracker window gets the Dock icon. -->
  <key>LSUIElement</key>                  <true/>
  <key>NSHighResolutionCapable</key>      <true/>
  <key>NSCameraUsageDescription</key>
  <string>Hand Mouse watches your hand through the camera to move the pointer. Video is processed on your Mac and never leaves it.</string>
</dict>
</plist>
EOF

echo "Built: $APP"
if [ "$(uname)" = "Darwin" ]; then
  xattr -cr "$APP" 2>/dev/null || true
  echo "Drag it to Applications, then double-click it."
fi
