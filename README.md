# Hand Mouse

Control your Mac's mouse with hand gestures, using the built-in camera.
Hand tracking runs entirely on your Mac (Google MediaPipe); nothing is uploaded.

## Install the app

1. Download **Hand-Mouse-app.zip** from the
   [latest release](https://github.com/rdydygin/handmouse/releases/latest), or build it yourself
   with `./build_app.sh` (creates `dist/Hand Mouse.app`).
   Unzip it and drag **Hand Mouse.app** into your **Applications** folder.
2. Double-click it. The app isn't from the App Store, so macOS blocks it the first time:
   - Click **Done** (or **Cancel**) in the warning.
   - Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to
     "Hand Mouse was blocked". Confirm with your password.

   You only do this once.
3. **First launch takes 2–5 minutes** and needs internet. The app installs its own private copy of
   Python and the hand-tracking libraries (about 600 MB) into
   `~/Library/Application Support/HandMouse`. Nothing else on your Mac is touched, and you don't
   need Homebrew or Terminal. Later launches start in a few seconds.
4. Approve two permissions when macOS asks:
   - **Camera**: click **Allow**.
   - **Accessibility** (lets it move the pointer): click **Open System Settings** and switch on
     **Hand Mouse**. Until then a red banner in the window says cursor control is off. If the
     pointer still doesn't move once it's switched on, quit Hand Mouse (press `q`) and open it again.

To quit, press `q` in the Hand Mouse window, close the window, or press ⌘Q.

### Updates

Hand Mouse updates itself. When it opens, and then about once a day while it's running, it checks
the [latest release](https://github.com/rdydygin/handmouse/releases/latest) in the background. When
a newer version is out, it downloads it and installs it the next time you open Hand Mouse; a
notification confirms the new version. Your settings are kept. To turn this off, add the line
`--no-auto-update` to the settings file.

The update status is shown at the bottom of the Hand Mouse window, e.g.
`Updates: Up to date (checked 2 h ago)`, `Updates: Downloading version 1.6.3...` or
`Updates: Version 1.6.3 ready: reopen Hand Mouse to install`. Press `u` in the window to check
right now. With auto-update off, `u` still tells you whether a newer version is available.

Updates are only installed when the app can replace itself: keep it in **Applications** and run it
from an account that can change that folder (an admin account).

### Settings

Press `s` in the Hand Mouse window to open the settings file in TextEdit. Remove the `#` in front of
an option to turn it on, save, then quit and reopen Hand Mouse. The options are explained in the
file and in [Tuning](#tuning) below.

### Uninstall

Delete **Hand Mouse.app** and the folder `~/Library/Application Support/HandMouse`.
In Finder, press ⌘⇧G and paste the path to get there.

## Run from Terminal instead (for development)

```bash
./run.sh
```

When run this way, the Camera and Accessibility permissions go to your terminal app
(Terminal, iTerm, VS Code...), not to Hand Mouse. After editing `hand_mouse.py`, run `./build_app.sh`
to rebuild `dist/Hand Mouse.app`.

## Gestures

Hold one hand up, palm toward the camera, about 40–70 cm from the screen. Either hand works.

| Action        | Gesture |
|---------------|---------|
| Move          | Move your hand. The cursor follows the base of your index finger. |
| Left click    | Quickly tap thumb and index fingertips together. |
| Double click  | Tap twice quickly. |
| Drag          | Pinch thumb + index, move, release. |
| Right click   | Tap thumb and **middle** fingertips together. |
| Scroll        | ✌️ Peace sign (index + middle up, ring + pinky folded), then **tilt** your fingers toward the camera to scroll down, or back to scroll up, keeping your wrist where it is. It works like a joystick: tilt further to scroll faster, hold the tilt to keep scrolling, straighten up to stop. The top bar shows the tilt in degrees; small tilts (under about 10°) do nothing. You can also move your whole hand up/down instead: flick and then drop the peace sign to let it coast, like a trackpad. Make the peace sign again (or click) to stop the coasting. |
| Switch desktop | **Four fingers** up with your **thumb tucked** across your palm (toward the base of your ring finger), then a quick flick **left or right**: switches desktops / full-screen apps, like a 4-finger trackpad swipe. Flick left = next desktop, right = previous. A flick of the wrist is enough: swing your fingers sideways like a windshield wiper (about 20°) without moving your hand across the frame. The cursor holds still while your thumb is tucked (the window shows `SWIPE`). |
| Swipe         | ✌️ Peace sign + a quick flick **left or right** (a wrist flick is enough here too) also switches desktops. Can be set to browser back/forward instead, so the two swipes do different things. |
| Re-center     | ✊ Make a fist: the cursor stays put while you move your hand back to a comfortable spot. Open your hand to continue. Like lifting a mouse off the desk. |
| Ignore hand   | Turn the **back** of your hand to the camera: it isn't tracked (the window shows `BACK OF HAND`), so you can rest it or type without moving the cursor. Show your palm again to continue. |
| Pause/resume  | Press `p` or space in the Hand Mouse window. |
| Check for updates | Press `u` in the Hand Mouse window (app only). |
| Quit          | Press `q` or Esc in the Hand Mouse window (or ⌘Q, or close the window). |

The preview window shows your tracked hand, the current mode, and live pinch values
(`pinch L` / `R`): a click fires when the value drops below 0.28.
The version number is in the top bar, next to the frame rate (`./run.sh --version` from Terminal).

## Tuning

In the app, put these in the settings file (press `s`). From Terminal, pass them to `./run.sh`
(all options: `./run.sh --help`).

| Option | Default | What it does |
|---|---|---|
| `--speed 0.5` | 0.65 | Cursor speed. Lower is slower; try 0.9 for faster. |
| `--reach 0.35` | 0.45 | Share of the camera width you sweep to cross the whole screen. Smaller means less arm movement. |
| `--smoothing 1.5` | 1.0 | Steadier cursor with a little more lag. Lower it if the cursor feels sluggish. |
| `--absolute` | off | Hand position maps directly to screen position, instead of trackpad-style relative movement. |
| `--pinch-on 0.33` | 0.28 | Make clicks trigger more easily. Lower it if you get accidental clicks. |
| `--invert-scroll` | off | Flip scroll direction. |
| `--swipe-action browser` | desktops | Make peace-sign swipes go back/forward in the browser and Finder (⌘[ / ⌘]) instead of switching desktops. `off` disables peace-sign swipes. |
| `--no-four-finger-swipe` | off | Turn off the four-finger flick (thumb tucked) that switches desktops. |
| `--scroll-speed 5000` | 3500 | Faster scrolling when you move your hand. |
| `--tilt-scroll-speed 2000` | 1200 | Faster tilt scrolling: pixels per second with the hand tilted about 30°. |
| `--no-tilt` | off | Tilting the hand doesn't scroll or swipe; only moving it does. |
| `--camera 1` | 0 | Use a different camera, e.g. if an iPhone Continuity Camera took index 0. |
| `--allow-back-of-hand` | off | Keep tracking the hand when its back faces the camera. |
| `--dry-run` | off | Track and print actions without touching the mouse. |
| `--no-preview` | off | Run without the camera window. |

Example: `./run.sh --speed 1.4 --smoothing 1.3`

## Tips

- Even, front-facing light helps a lot. A bright window behind you makes tracking worse.
- Keep your wrist in view; tracking drops near the edges of the frame.
- If the cursor drifts to a screen edge, make a fist, move your hand back to the centre and open it.
- Clicks land where the cursor is when you pinch: point first, then tap.

## How it works

- `hand_mouse.py`: the whole app. MediaPipe Hand Landmarker finds 21 hand points per camera frame.
  A gesture engine turns them into pointer motion (palm centre, One Euro filter, pointer
  acceleration), pinch clicks (with hysteresis), and scroll, four-finger swipe and fist poses (debounced).
  Tilt scrolling and wrist-flick swipes use MediaPipe's 3D world landmarks to measure how the palm
  leans toward the camera and sideways. A 120 Hz
  thread glides the cursor and scroll between camera frames. Events are posted with macOS Quartz
  (`CGEventPost`), so drags, double-clicks and smooth scrolling behave like real hardware.
- `assets/launcher.sh`: the app's executable. On first launch it installs a private Python 3.12 and
  the dependencies with [uv](https://github.com/astral-sh/uv) into `~/Library/Application Support/HandMouse`.
  It also does the auto-update: it checks the GitHub releases API, downloads `Hand-Mouse-app.zip`
  into `~/Library/Application Support/HandMouse/update`, and swaps the new app in on the next launch.
  It writes the current state to `update/status`, which the window shows; pressing `u` creates
  `update/check-now` to ask for an immediate check.
- `build_app.sh`: assembles `Hand Mouse.app` (Info.plist with the camera usage text, icon, model).
- `.github/workflows/release.yml`: builds the app and publishes a GitHub release for every push to
  `main`. Installed apps update from these releases.
- `run.sh`: runs from Terminal for development.

## Publishing a release

Every push to `main` (including merged pull requests) publishes a new release automatically.
GitHub Actions builds `Hand-Mouse-app.zip` and picks the version from `VERSION` in `build_app.sh`:

- the first release after `VERSION` changes is `v<VERSION>` (e.g. `v1.7`);
- every later push adds a patch number: `v1.7.1`, `v1.7.2`, ...

So for a normal change there's nothing to do. For a bigger release, bump `VERSION` (e.g. to `1.8`)
in the same pull request. Installed copies pick up a new release within a day, or right away when
`u` is pressed in the window. You can also re-run the release by hand from the Actions tab
(**Release → Run workflow**); a commit that already has a release is skipped.

## Troubleshooting

- **Pointer doesn't move but the window shows "MOVE"**: turn on Hand Mouse in *System Settings →
  Privacy & Security → Accessibility*, then quit and reopen it. If it's already on, remove it with
  the **–** button, reopen Hand Mouse and allow it again. This also applies after moving the app
  to a different folder.
- **No camera prompt, or "can't use the camera"**: turn on Hand Mouse in *Privacy & Security →
  Camera*. If it isn't listed, reset the permission in Terminal and reopen the app:
  `tccutil reset Camera local.handmouse.app`
- **Setup failed or the app quits right away**: the log is at `~/Library/Logs/HandMouse.log`.
  To reinstall from scratch, delete `~/Library/Application Support/HandMouse` and open the app again.
- **Not updating**: the bottom of the Hand Mouse window shows the update status (press `u` to check
  now), and the log (`~/Library/Logs/HandMouse.log`) has an `Update check:` line for each check. Updates are skipped if `--no-auto-update` is in settings, if the app can't be replaced
  (not in Applications, or a non-admin account), or if it's running straight from Downloads.
- **Wrong camera** (e.g. your iPhone via Continuity Camera): set `--camera 1` in settings.
- **Running from Terminal on an Intel Mac and the install fails**: MediaPipe needs Python 3.12 or
  older there: `brew install python@3.12 && rm -rf .venv && ./run.sh`. The app handles this itself.
- **Swipes don't switch desktops**: you need more than one desktop (add one in Mission Control), and
  the shortcuts must be on in *System Settings → Keyboard → Keyboard Shortcuts → Mission Control*
  ("Move left a space" / "Move right a space").
- **Multiple monitors**: the cursor is limited to the main display.

## License

MIT
