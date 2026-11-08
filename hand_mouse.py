#!/usr/bin/env python3
"""
Hand Mouse: control your Mac's mouse with hand gestures through the webcam.

Gestures (palm toward the camera, either hand):
  Move          move your hand; the cursor follows the base of your index finger
  Left click    quick tap of thumb + index fingertips
  Double click  two quick taps
  Drag          pinch thumb + index, move, release
  Right click   tap thumb + middle fingertips
  Scroll        "peace sign" (index + middle up, others folded), then tilt your
                fingers toward the camera (scroll down) or back (scroll up); the
                further you tilt, the faster. Or move the hand up/down: flick and
                change pose to let it coast, like a trackpad
  Swipe         three fingers up (index + middle + ring, pinky folded) + quick
                flick left/right: switch desktops, like a 3-finger trackpad swipe.
                Swinging the fingers sideways from the wrist (like a windshield
                wiper) is enough; the hand doesn't have to travel.
                (the peace sign flicks too; --swipe-action browser makes the
                peace-sign flick go back/forward in the browser instead)
  Clutch        make a fist: the cursor stops so you can re-center your hand,
                like lifting a mouse off the desk
  Ignore        turn the back of your hand to the camera: it's not tracked, so you
                can rest it or use the keyboard without moving the cursor

Keys (preview window focused):  q / Esc = quit,  p / space = pause / resume,
                                s = settings (app only)
"""

import argparse
import atexit
import collections
import json
import math
import os
import platform
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

HERE = os.path.dirname(os.path.abspath(__file__))


def app_version():
    """The app passes its version in HANDMOUSE_VERSION (from Info.plist). Run
    from the repository, read it from build_app.sh, the one place it's set."""
    v = os.environ.get("HANDMOUSE_VERSION")
    if v:
        return v
    try:
        with open(os.path.join(HERE, "build_app.sh")) as f:
            for line in f:
                if line.startswith("VERSION="):
                    return line[len("VERSION="):].split()[0] + "-dev"
    except OSError:
        pass
    return "dev"


VERSION = app_version()
MODEL_PATH = os.path.join(HERE, "models", "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")

# MediaPipe hand landmark indices
WRIST, THUMB_TIP = 0, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_PIP, PINKY_TIP = 18, 20
FINGERS = {"index": (INDEX_PIP, INDEX_TIP), "middle": (MIDDLE_PIP, MIDDLE_TIP),
           "ring": (RING_PIP, RING_TIP), "pinky": (PINKY_PIP, PINKY_TIP)}
PINKY_MCP = 17
PALM = (WRIST, INDEX_MCP, MIDDLE_MCP, 13, PINKY_MCP)

# Cursor feel. Filter: lower MIN_CUTOFF = steadier when still; higher BETA =
# less lag when moving fast. Acceleration: GAIN_MIN applies to slow movements
# (below V_LOW px/s), GAIN_MAX to fast ones (above V_HIGH px/s).
FILTER_MIN_CUTOFF, FILTER_BETA = 0.5, 0.006
GAIN_MIN, GAIN_MAX, V_LOW, V_HIGH = 0.2, 1.6, 80, 900

# Scrolling: hand speeds below SCROLL_DEADZONE (frame heights/s) are ignored so a
# still hand doesn't creep; SCROLL_GLIDE (s) smooths output between frames; a
# flick faster than MOMENTUM_MIN px/s coasts, fading over MOMENTUM_DECAY s.
SCROLL_DEADZONE, SCROLL_GLIDE = 0.04, 0.05
MOMENTUM_MIN, MOMENTUM_DECAY = 700, 0.35
# Swipes: peace sign or three fingers moved sideways by SWIPE_DIST of the frame width within
# SWIPE_WINDOW seconds, mostly horizontally. One swipe per SWIPE_COOLDOWN seconds.
SWIPE_DIST, SWIPE_WINDOW, SWIPE_COOLDOWN = 0.13, 0.3, 0.8
# Tilting instead of moving the hand (the wrist stays put, so the hand stays in view).
# Swipe: the fingers swing sideways by SWIPE_ANGLE degrees within SWIPE_WINDOW (this
# adds up with sideways hand travel). Scroll: the fingers lean toward / away from the
# camera more than TILT_DEADZONE degrees from where they were when the peace sign
# began; TILT_FULL degrees past that scrolls at --tilt-scroll-speed, and further
# tilts go faster, up to TILT_MAX times that. Within the dead zone the rest
# position follows the hand over TILT_ADAPT seconds, so slow drift doesn't scroll.
SWIPE_ANGLE = 22
TILT_DEADZONE, TILT_FULL, TILT_MAX, TILT_ADAPT = 10, 20, 2.0, 2.0
# Back of the hand toward the camera: palm_side() below this (and above minus
# this for palm) counts; in between (hand edge-on) is ambiguous. Frames in a row
# needed to stop tracking / resume it: quick to let go, slower to pick back up.
PALM_SIDE_MIN, BACK_FRAMES, PALM_FRAMES = 0.2, 2, 3
KEY_LEFT, KEY_RIGHT, KEY_LBRACKET, KEY_RBRACKET = 123, 124, 33, 30
HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
                    (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


# --------------------------------------------------------------------------- #
# Mouse backends
# --------------------------------------------------------------------------- #
class MacMouse:
    """Posts real mouse events through Quartz, so drags and double-clicks behave
    like a physical mouse (pyautogui gets both of these wrong on macOS)."""

    def __init__(self):
        import Quartz as Q
        self.Q = Q
        bounds = Q.CGDisplayBounds(Q.CGMainDisplayID())
        self.width, self.height = int(bounds.size.width), int(bounds.size.height)
        loc = Q.CGEventGetLocation(Q.CGEventCreate(None))
        self.x, self.y = float(loc.x), float(loc.y)
        self.is_down = False
        self._click_state = 1
        self._last_up = (0.0, 0.0, 0.0)  # time, x, y
        try:
            from AppKit import NSEvent
            self._dbl_interval = float(NSEvent.doubleClickInterval())
        except Exception:
            self._dbl_interval = 0.5

    def _post(self, etype, button, click_state=None):
        Q = self.Q
        ev = Q.CGEventCreateMouseEvent(None, etype, (self.x, self.y), button)
        if click_state is not None:
            Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, click_state)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def move(self, x, y):
        Q = self.Q
        self.x = min(max(x, 0), self.width - 1)
        self.y = min(max(y, 0), self.height - 1)
        if self.is_down:
            self._post(Q.kCGEventLeftMouseDragged, Q.kCGMouseButtonLeft, self._click_state)
        else:
            self._post(Q.kCGEventMouseMoved, Q.kCGMouseButtonLeft)

    def left_down(self):
        t, lx, ly = self._last_up
        close = math.hypot(self.x - lx, self.y - ly) < 12
        self._click_state = self._click_state + 1 if (time.monotonic() - t < self._dbl_interval and close) else 1
        self.is_down = True
        self._post(self.Q.kCGEventLeftMouseDown, self.Q.kCGMouseButtonLeft, self._click_state)

    def left_up(self):
        if not self.is_down:
            return
        self.is_down = False
        self._post(self.Q.kCGEventLeftMouseUp, self.Q.kCGMouseButtonLeft, self._click_state)
        self._last_up = (time.monotonic(), self.x, self.y)

    def right_click(self):
        Q = self.Q
        self._post(Q.kCGEventRightMouseDown, Q.kCGMouseButtonRight, 1)
        self._post(Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight, 1)

    def scroll(self, pixels):
        Q = self.Q
        ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 1, int(pixels))
        # Mark as continuous (trackpad-style) so apps scroll smoothly by pixels
        # instead of in mouse-wheel notches.
        Q.CGEventSetIntegerValueField(ev, Q.kCGScrollWheelEventIsContinuous, 1)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def hotkey(self, keycode, modifier):
        """Press a key with Control or Command held, like a real keyboard would."""
        Q = self.Q
        mod_key, mask = {"ctrl": (59, Q.kCGEventFlagMaskControl),
                         "cmd": (55, Q.kCGEventFlagMaskCommand)}[modifier]
        flags = mask
        if keycode in (123, 124, 125, 126):   # arrow keys carry these flags on real keyboards
            flags |= Q.kCGEventFlagMaskSecondaryFn | Q.kCGEventFlagMaskNumericPad
        for code, down, f in ((mod_key, True, mask), (keycode, True, flags),
                              (keycode, False, flags), (mod_key, False, 0)):
            ev = Q.CGEventCreateKeyboardEvent(None, code, down)
            Q.CGEventSetFlags(ev, f)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)


class DryRunMouse:
    """Moves nothing; records what would happen. Used by --dry-run and off macOS."""

    def __init__(self, width=1440, height=900, verbose=False):
        self.width, self.height = width, height
        self.x, self.y = width / 2, height / 2
        self.is_down = False
        self.verbose = verbose
        self.events = []

    def _log(self, *e):
        self.events.append(e)
        if self.verbose:
            print("[dry-run]", *e)

    def move(self, x, y):
        self.x = min(max(x, 0), self.width - 1)
        self.y = min(max(y, 0), self.height - 1)
        self.events.append(("move", round(self.x), round(self.y)))

    def left_down(self):
        self.is_down = True
        self._log("left_down", round(self.x), round(self.y))

    def left_up(self):
        if self.is_down:
            self.is_down = False
            self._log("left_up", round(self.x), round(self.y))

    def right_click(self):
        self._log("right_click", round(self.x), round(self.y))

    def scroll(self, pixels):
        self.events.append(("scroll", int(pixels)))

    def scroll_momentum(self, velocity):
        if velocity:
            self._log("momentum", round(velocity))

    def hotkey(self, keycode, modifier):
        self._log("hotkey", modifier, keycode)


class SmoothMouse:
    """Wraps a mouse backend and glides the real cursor toward its target 120
    times a second. The camera only delivers 15-30 frames a second; moving the
    cursor once per frame looks steppy and jittery even when tracking is good."""

    def __init__(self, backend, rate=120, tau=0.03):
        self.b = backend
        self.width, self.height = backend.width, backend.height
        self.x, self.y = backend.x, backend.y   # target
        self._lock = threading.Lock()
        self._rate, self._tau = rate, tau
        self._scroll_pending = 0.0   # px still to scroll
        self._scroll_carry = 0.0     # fraction of a px not yet sent
        self._momentum = 0.0         # px/s of coasting scroll
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def is_down(self):
        return self.b.is_down

    def _run(self):
        dt = 1.0 / self._rate
        alpha = 1 - math.exp(-dt / self._tau)
        s_alpha = 1 - math.exp(-dt / SCROLL_GLIDE)
        decay = math.exp(-dt / MOMENTUM_DECAY)
        while True:
            time.sleep(dt)
            with self._lock:
                dx, dy = self.x - self.b.x, self.y - self.b.y
                if abs(dx) > 0.3 or abs(dy) > 0.3:
                    self.b.move(self.b.x + dx * alpha, self.b.y + dy * alpha)
                # Scroll: spread each camera frame's amount over several ticks,
                # and let a flick coast to a stop.
                if self._momentum:
                    self._scroll_pending += self._momentum * dt
                    self._momentum *= decay
                    if abs(self._momentum) < 20:
                        self._momentum = 0.0
                if self._scroll_pending:
                    out = self._scroll_pending if abs(self._scroll_pending) < 1 else self._scroll_pending * s_alpha
                    self._scroll_pending -= out
                    self._scroll_carry += out
                    n = int(self._scroll_carry)
                    if n:
                        self.b.scroll(n)
                        self._scroll_carry -= n

    def move(self, x, y):
        with self._lock:
            self.x = min(max(x, 0), self.width - 1)
            self.y = min(max(y, 0), self.height - 1)

    def _snap(self):   # buttons act exactly where the cursor is headed
        if abs(self.x - self.b.x) > 0.3 or abs(self.y - self.b.y) > 0.3:
            self.b.move(self.x, self.y)

    def left_down(self):
        with self._lock:
            self._snap(); self.b.left_down()

    def left_up(self):
        with self._lock:
            self._snap(); self.b.left_up()

    def right_click(self):
        with self._lock:
            self._snap(); self.b.right_click()

    def scroll(self, pixels):
        with self._lock:
            self._scroll_pending += pixels

    def scroll_momentum(self, velocity):
        """Coast at `velocity` px/s, slowing to a stop. 0 stops any coasting."""
        with self._lock:
            self._momentum = velocity
            if not velocity:
                self._scroll_pending = 0.0

    def hotkey(self, keycode, modifier):
        with self._lock:
            self.b.hotkey(keycode, modifier)


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
class OneEuro:
    """One Euro filter: heavy smoothing when the hand is still (kills jitter),
    light smoothing when it moves fast (keeps the cursor responsive)."""

    def __init__(self, min_cutoff=1.0, beta=0.005, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.t = self.x = None
        self.dx = 0.0

    @staticmethod
    def _alpha(dt, cutoff):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.t, self.x = t, x
            return x
        dt = max(t - self.t, 1e-4)
        a_d = self._alpha(dt, self.d_cutoff)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        a = self._alpha(dt, self.min_cutoff + self.beta * abs(self.dx))
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x


# --------------------------------------------------------------------------- #
# Gesture engine
# --------------------------------------------------------------------------- #
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_side(lms, handedness, frame_aspect):
    """How squarely the palm faces the camera: about +0.7 for a flat palm, -0.7
    for the back of the hand, near 0 edge-on. `lms` are landmarks of the mirrored
    frame and `handedness` is MediaPipe's "Left"/"Right" label for that frame.
    The wrist -> index knuckle -> pinky knuckle triangle winds one way when the
    palm faces the camera and the other way when the back does, and the way it
    winds depends on which hand it is. (Checked against MediaPipe's own palm and
    back-of-hand test photos.)"""
    P = [(x * frame_aspect, y) for x, y in lms]
    wx, wy = P[WRIST]
    ax, ay = P[INDEX_MCP][0] - wx, P[INDEX_MCP][1] - wy
    bx, by = P[PINKY_MCP][0] - wx, P[PINKY_MCP][1] - wy
    size2 = _dist(P[WRIST], P[MIDDLE_MCP]) ** 2 or 1e-6
    cross = (ax * by - ay * bx) / size2
    return cross if handedness == "Left" else -cross


def hand_angles(world):
    """(roll, pitch) of the palm in degrees, from MediaPipe's 3D world landmarks
    of the mirrored frame (x right, y down, z away from the camera). Both are 0
    for an upright hand. roll > 0: fingers lean right in the picture, < 0: left
    (a windshield-wiper turn at the wrist). pitch > 0: fingers lean toward the
    camera, < 0: away. Measured along the palm (wrist -> middle knuckle), so
    bending the fingers doesn't change it."""
    (wx, wy, wz), (mx, my, mz) = world[WRIST], world[MIDDLE_MCP]
    dx, dy, dz = mx - wx, my - wy, mz - wz
    return (math.degrees(math.atan2(dx, -dy)),
            math.degrees(math.atan2(-dz, math.hypot(dx, dy))))


def _angle_diff(a, b):
    return (a - b + 180) % 360 - 180


class GestureEngine:
    def __init__(self, mouse, cfg):
        self.mouse = mouse
        self.cfg = cfg
        self.fx = OneEuro(FILTER_MIN_CUTOFF / cfg.smoothing, FILTER_BETA)
        self.fy = OneEuro(FILTER_MIN_CUTOFF / cfg.smoothing, FILTER_BETA)
        self.prev_t = None
        self.pose, self.pose_candidate, self.pose_count = "open", "open", 0
        self.paused = False
        self.mode = "no hand"
        self.left = self.right = False
        self.dragging = False
        self.drag_travel = 0.0
        self.freeze_until = 0.0
        self.prev = None          # previous filtered target, screen px
        self.scroll_prev = None
        self.scroll_v = 0.0                    # recent scroll speed, px/s
        self.sf = OneEuro(1.5, 0.8)            # scroll-position filter (frame units)
        self.swipe_hist = collections.deque()  # (t, x, y, roll, pitch) in scroll / swipe pose
        self.pf = OneEuro(1.0, 0.02)           # pitch filter (degrees)
        self.tilt_rest = None                  # pitch where tilt scrolling is still
        self.tilt_rest_t = 0.0                 # last time it was used
        self.tilt = 0.0                        # current tilt past the rest position (HUD)
        self.swipe_ready_at = 0.0
        self.flash, self.flash_until = "", 0.0 # short on-screen message (e.g. swipe)
        self.last_seen = 0.0
        self.facing_away = False               # back of the hand toward the camera
        self.back_n = self.palm_n = 0
        self.metrics = {}
        self.cx, self.cy = mouse.x, mouse.y   # virtual cursor (relative mode)

    # Active camera region that maps onto the whole screen (absolute mode) and
    # sets the gain (relative mode). Same scale on both axes so motion feels even.
    def region(self, frame_aspect):
        rw = self.cfg.reach
        rh = rw * (self.mouse.height / self.mouse.width) * frame_aspect
        rh = min(rh, 0.9)
        cx, cy = 0.5, 0.45
        return cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2

    def _to_screen(self, nx, ny, frame_aspect):
        x0, y0, x1, y1 = self.region(frame_aspect)
        return ((nx - x0) / (x1 - x0) * self.mouse.width,
                (ny - y0) / (y1 - y0) * self.mouse.height)

    def release_all(self):
        if self.left:
            self.mouse.left_up()
        self.left = self.right = self.dragging = False

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.release_all()
        self.prev = None

    def _swipe_motion(self):
        """Sideways and vertical motion over the last SWIPE_WINDOW, in units where
        1 = a full swipe: hand travel / SWIPE_DIST plus finger swing / SWIPE_ANGLE.
        Also returns just the sideways swing in degrees."""
        h = self.swipe_hist
        _, x0, y0, r0, p0 = h[0]
        _, x1, y1, r1, p1 = h[-1]
        # sx is signed (direction of the swipe); sy only needs a size, and both of
        # its parts count as vertical, so add magnitudes: they must not cancel.
        sx, sy, swing = (x1 - x0) / SWIPE_DIST, abs(y1 - y0) / SWIPE_DIST, 0.0
        if r0 is not None and r1 is not None:
            swing = _angle_diff(r1, r0)
            sx += swing / SWIPE_ANGLE
            sy += abs(p1 - p0) / SWIPE_ANGLE
        return sx, sy, swing

    def _flick(self, ax, ay, angles, t, enabled=True):
        """Track the wrist and the hand's angles; on a quick, mostly horizontal
        flick (hand travel, a sideways swing of the fingers, or both) return True
        (moved left: next desktop / forward) or False (right). Otherwise None."""
        h = self.swipe_hist
        roll, pitch = angles if angles else (None, None)
        h.append((t, ax, ay, roll, pitch))
        while h and t - h[0][0] > SWIPE_WINDOW:
            h.popleft()
        sx, sy, _ = self._swipe_motion()
        if (enabled and t >= self.swipe_ready_at
                and abs(sx) > 1 and abs(sx) > 2 * abs(sy)):
            self.swipe_ready_at = t + SWIPE_COOLDOWN
            h.clear()
            return sx < 0   # hand moves left -> content follows -> next desktop / forward
        return None

    def _switch_desktop(self, nxt, t):
        self.mouse.hotkey(KEY_RIGHT if nxt else KEY_LEFT, "ctrl")
        self.flash = "DESKTOP >" if nxt else "< DESKTOP"
        self.flash_until = t + 0.7

    def _scroll_and_swipe(self, ax, ay, angles, raw_pose, dt, t):
        cfg, m = self.cfg, self.mouse
        if self.scroll_prev is None:   # entering the pose: stop any coasting
            m.scroll_momentum(0)
            self.sf.reset()
            self.pf.reset()
            self.swipe_hist.clear()
            self.scroll_v = 0.0
            # A pose that flickers off for a moment mid-tilt keeps its rest position.
            if t - self.tilt_rest_t > 1.0:
                self.tilt_rest = None
        y = self.sf(ay, t)
        self.mode = "scroll"

        # Swipe: a quick, mostly horizontal flick.
        h = self.swipe_hist
        nxt = self._flick(ax, ay, angles, t, enabled=cfg.swipe_action != "off")
        if nxt is not None:
            if cfg.swipe_action == "browser":
                m.hotkey(KEY_RBRACKET if nxt else KEY_LBRACKET, "cmd")
                self.flash = "FORWARD >" if nxt else "< BACK"
                self.flash_until = t + 0.7
            else:
                self._switch_desktop(nxt, t)
            m.scroll_momentum(0)
            self.scroll_v = 0.0
        sideways = len(h) > 1 and ((abs(ax - h[0][1]) > 1.5 * abs(ay - h[0][2]) and abs(ax - h[0][1]) > 0.03)
                                   or abs(self._swipe_motion()[2]) > SWIPE_ANGLE / 2)
        settled = raw_pose == "scroll" and not sideways and t >= self.swipe_ready_at - SWIPE_COOLDOWN + 0.4

        # Tilt scroll: like a joystick, lean the fingers toward the camera to scroll
        # down, away to scroll up; the further, the faster. Hold the tilt to keep going.
        self.tilt = 0.0
        if angles is not None:
            pitch = self.pf(angles[1], t)
            if self.tilt_rest is None:
                self.tilt_rest = pitch
            self.tilt_rest_t = t
            off = pitch - self.tilt_rest
            if abs(off) <= TILT_DEADZONE:
                self.tilt_rest += off * min(dt / TILT_ADAPT, 1.0)
            else:
                self.tilt = off
                if settled:
                    f = min((abs(off) - TILT_DEADZONE) / TILT_FULL, TILT_MAX)
                    rate = -math.copysign(f * f * cfg.tilt_scroll_speed, off)
                    m.scroll(rate * (-1 if cfg.invert_scroll else 1) * dt)

        # Scroll speed follows hand speed (smoothed, with a small dead zone).
        if self.scroll_prev is not None and settled:
            v = (y - self.scroll_prev) / dt                       # frame heights / s
            v = math.copysign(max(abs(v) - SCROLL_DEADZONE, 0.0), v)
            px_per_s = v * cfg.scroll_speed * (-1 if cfg.invert_scroll else 1)
            self.scroll_v = 0.5 * self.scroll_v + 0.5 * px_per_s
            if px_per_s:
                m.scroll(px_per_s * dt)
        elif raw_pose == "scroll":
            self.scroll_v = 0.0
        self.scroll_prev = y

    def _hand_gone(self, t):
        if self.left and t - self.last_seen > 0.3:   # lost hand mid-drag
            self.release_all()
        if t - self.last_seen > 0.3:
            self.prev = None
            self.fx.reset(); self.fy.reset()
        self.scroll_prev, self.scroll_v = None, 0.0

    def _check_facing(self, lms, handedness, frame_aspect):
        """Track whether the back of the hand faces the camera (with debouncing)."""
        side = palm_side(lms, handedness, frame_aspect)
        if side < -PALM_SIDE_MIN:
            self.back_n, self.palm_n = self.back_n + 1, 0
        elif side > PALM_SIDE_MIN:
            self.palm_n, self.back_n = self.palm_n + 1, 0
        else:   # edge-on: keep the current state, but the run of evidence is broken
            self.back_n = self.palm_n = 0
        if self.back_n >= BACK_FRAMES:
            self.facing_away = True
        elif self.palm_n >= PALM_FRAMES:
            self.facing_away = False

    def update(self, lms, frame_aspect, t, handedness=None, world=None):
        """lms: 21 (x, y) normalized landmarks of a mirrored frame, or None.
        handedness: MediaPipe's "Left"/"Right" label for the hand; if given, a
        hand showing its back to the camera is ignored. world: the matching 21
        (x, y, z) 3D world landmarks; if given, tilting the hand scrolls and swipes."""
        cfg, m = self.cfg, self.mouse

        if lms is not None and handedness and not cfg.allow_back_of_hand:
            self._check_facing(lms, handedness, frame_aspect)
            if self.facing_away:
                self._hand_gone(t)
                # Turning the hand moves the palm centre, so don't let the cursor
                # jump by that much when the palm comes back.
                self.prev = None
                self.fx.reset(); self.fy.reset()
                self.pose_candidate, self.pose_count = "open", 0
                self.mode = "paused" if self.paused else "back of hand"
                return

        if lms is None:
            self._hand_gone(t)
            self.back_n = self.palm_n = 0
            self.mode = "paused" if self.paused else "no hand"
            return
        self.last_seen = t

        # Isotropic coordinates so distances don't depend on the camera aspect.
        P = [(x * frame_aspect, y) for x, y in lms]
        size = _dist(P[WRIST], P[MIDDLE_MCP]) or 1e-6
        d_left = _dist(P[THUMB_TIP], P[INDEX_TIP]) / size
        d_right = _dist(P[THUMB_TIP], P[MIDDLE_TIP]) / size
        # Finger straightness: wrist-to-tip vs wrist-to-middle-joint. Straight ~1.4,
        # curled into the palm ~0.8. Half-curled fingers (a relaxed hand) count as
        # neither, so they can't accidentally trigger scroll or fist.
        ratio = {f: _dist(P[WRIST], P[tip]) / (_dist(P[WRIST], P[pip]) or 1e-6)
                 for f, (pip, tip) in FINGERS.items()}
        ext = {f: r > 1.15 for f, r in ratio.items()}
        folded = {f: r < 0.95 for f, r in ratio.items()}
        if ext["index"] and ext["middle"] and folded["ring"] and folded["pinky"]:
            raw_pose = "scroll"
        # Three fingers up. Few people can fold the pinky all the way with the ring
        # finger straight, so a pinky that's merely bent counts.
        elif ext["index"] and ext["middle"] and ext["ring"] and ratio["pinky"] < 1.05:
            raw_pose = "swipe"
        elif all(folded.values()):
            raw_pose = "fist"
        else:
            raw_pose = "open"
        # A pose must hold for a few frames before it counts (no flicker).
        if raw_pose == self.pose_candidate:
            self.pose_count += 1
        else:
            self.pose_candidate, self.pose_count = raw_pose, 1
        if self.pose_count >= 3:
            self.pose = raw_pose
        self.metrics = {"left": d_left, "right": d_right, "ext": ext}

        # Pinch detection with hysteresis (easier to press than to release).
        left_now = d_left < (cfg.pinch_off if self.left else cfg.pinch_on)
        right_now = d_right < (cfg.pinch_off if self.right else cfg.pinch_on)
        # Only one pinch at a time: whichever is held wins; on a tie, the tighter one.
        if self.left:
            right_now = False
        elif self.right:
            left_now = False
        elif left_now and right_now:
            left_now, right_now = d_left <= d_right, d_right < d_left

        # Filtered pointer target in screen pixels. Anchor on the palm centre (wrist
        # + four knuckles): averaging five points cancels much of the tracking
        # noise, and the palm stays put when you pinch, so clicks land on target.
        ax = sum(lms[i][0] for i in PALM) / len(PALM)
        ay = sum(lms[i][1] for i in PALM) / len(PALM)
        # Scrolls and swipes follow the wrist instead: it stays put when the hand
        # tilts, so tilting doesn't also count as moving.
        wx, wy = lms[WRIST]
        angles = hand_angles(world) if world is not None and not cfg.no_tilt else None
        tx, ty = self._to_screen(ax, ay, frame_aspect)
        tx, ty = self.fx(tx, t), self.fy(ty, t)
        delta = (0.0, 0.0) if self.prev is None else (tx - self.prev[0], ty - self.prev[1])
        dt = max(t - self.prev_t, 1e-3) if self.prev_t is not None else 1 / 30
        self.prev, self.prev_t = (tx, ty), t
        # Pointer acceleration, like a trackpad: slow (aiming) motion is scaled
        # down so leftover hand tremor barely moves the cursor; fast motion is
        # scaled up so you can still cross the screen with a short sweep.
        v = math.hypot(*delta) / dt
        s_ = min(max((v - V_LOW) / (V_HIGH - V_LOW), 0.0), 1.0)
        gain = GAIN_MIN + (GAIN_MAX - GAIN_MIN) * s_ * s_ * (3 - 2 * s_)

        if self.paused:
            self.mode = "paused"
            return

        def move_cursor():
            if cfg.absolute:
                m.move(tx, ty)
            else:
                self.cx = min(max(self.cx + delta[0] * gain * cfg.speed, 0), m.width - 1)
                self.cy = min(max(self.cy + delta[1] * gain * cfg.speed, 0), m.height - 1)
                m.move(self.cx, self.cy)

        # --- Left button: click / double click / drag ---
        if left_now and not self.left:
            self.left, self.dragging, self.drag_travel = True, False, 0.0
            m.scroll_momentum(0)
            m.left_down()
        elif not left_now and self.left:
            self.left = False
            m.left_up()
            self.freeze_until = t + cfg.release_freeze   # opening fingers jiggles the hand
        if self.left:
            if not self.dragging:
                self.drag_travel += math.hypot(*delta)
                if self.drag_travel > cfg.drag_threshold:
                    self.dragging = True
            if self.dragging:
                move_cursor()
            self.mode = "drag" if self.dragging else "click"
            return

        # --- Right click (edge-triggered) ---
        if right_now and not self.right:
            self.right = True
            m.right_click()
        elif not right_now and self.right:
            self.right = False
            self.freeze_until = t + cfg.release_freeze
        if self.right:
            self.mode = "right click"
            return

        # --- Scroll / swipe: peace sign (index + middle up, ring + pinky folded) ---
        if self.pose == "scroll":
            self._scroll_and_swipe(wx, wy, angles, raw_pose, dt, t)
            return
        if self.scroll_prev is not None:   # just left the pose: let a flick coast
            if abs(self.scroll_v) > MOMENTUM_MIN:
                m.scroll_momentum(self.scroll_v)
            self.scroll_prev, self.scroll_v = None, 0.0

        # --- Three-finger swipe: flick left/right to switch desktops ---
        if self.pose == "swipe" and not cfg.no_three_finger_swipe:
            # self.mode still holds the last frame's mode, so this catches every way
            # into the pose (from scrolling, a click, a lost hand...).
            if self.mode != "swipe":   # entering the pose: stop any coasting
                m.scroll_momentum(0)
                self.swipe_hist.clear()
            self.mode = "swipe"     # cursor holds still, like a trackpad swipe
            nxt = self._flick(wx, wy, angles, t)
            if nxt is not None:
                self._switch_desktop(nxt, t)
            return

        # --- Fist: clutch (cursor holds still) ---
        if self.pose == "fist":
            self.mode = "fist (hold)"
            return

        self.mode = "move"
        if t >= self.freeze_until:
            move_cursor()


# --------------------------------------------------------------------------- #
# App integration (dialogs, Dock identity, permissions)
# --------------------------------------------------------------------------- #
APP_MODE = False          # set by --app (when launched from Hand Mouse.app)
EXIT_REPORTED = 3         # exit code telling the app launcher "already showed a dialog"
SETTINGS_PANES = {"camera": "Privacy_Camera", "accessibility": "Privacy_Accessibility"}


def alert(message, pane=None):
    """Show an error: a dialog when running as the app (with a button that opens
    the right System Settings page), plain text in a terminal."""
    print(message, file=sys.stderr)
    if not APP_MODE:
        return
    buttons = '{"Open System Settings", "OK"}' if pane else '{"OK"}'
    script = (f"display dialog {json.dumps(message, ensure_ascii=False)} with title \"Hand Mouse\" "
              f"buttons {buttons} default button \"OK\" with icon caution")
    try:
        r = subprocess.run(["osascript", "-e", "activate", "-e", f"button returned of ({script})"],
                           capture_output=True, text=True)
        if pane and r.stdout.strip() == "Open System Settings":
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?"
                            + SETTINGS_PANES[pane]])
    except OSError:
        pass


def setup_app_identity():
    """Give the Python process the app's name and icon in the Dock and menu bar."""
    try:
        from AppKit import NSApplication, NSBundle, NSImage
        from Foundation import NSProcessInfo
        try:
            info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = "Hand Mouse"
        except Exception:
            pass
        NSProcessInfo.processInfo().setProcessName_("Hand Mouse")
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(0)   # regular app: Dock icon, menu bar, keyboard focus
        icon = os.environ.get("HANDMOUSE_ICON")
        if icon and os.path.exists(icon):
            app.setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(icon))
        app.activateIgnoringOtherApps_(True)
    except Exception as e:
        print("Could not set app identity:", e, file=sys.stderr)


def accessibility_trusted(prompt=False):
    """Mouse events are silently dropped without Accessibility permission. In a
    terminal it belongs to the terminal app; as Hand Mouse.app, to the app."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception:
        return True   # can't tell; assume fine


# --------------------------------------------------------------------------- #
# Camera, model, preview
# --------------------------------------------------------------------------- #
def ensure_model(path=None):
    if path:
        return path
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        return MODEL_PATH
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    print("Downloading hand tracking model (~8 MB)...")
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    tmp = MODEL_PATH + ".part"
    with urllib.request.urlopen(MODEL_URL, context=ctx) as r, open(tmp, "wb") as f:
        f.write(r.read())
    os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


def open_camera(source):
    if not str(source).isdigit():          # video file (for testing)
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            alert(f"Could not open video file {source}.")
            sys.exit(EXIT_REPORTED)
        return cap
    # On first launch macOS shows a camera permission prompt and OpenCV fails
    # until it's answered, so keep retrying for a while instead of giving up.
    deadline = time.monotonic() + 60
    while True:
        cap = cv2.VideoCapture(int(source))
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            ok, _ = cap.read()
            if ok:
                return cap
        cap.release()
        if time.monotonic() > deadline:
            break
        time.sleep(1.0)
    who = "Hand Mouse" if APP_MODE else "your terminal app (Terminal, iTerm, VS Code...)"
    alert(f"Hand Mouse can't use the camera.\n\nIn System Settings > Privacy & Security > Camera, "
          f"turn on {who}, then open Hand Mouse again.\n\n"
          f"If you have several cameras, set a different one in Settings (press S in the window).",
          pane="camera")
    sys.exit(EXIT_REPORTED)


def draw_hud(frame, engine, lms, fps, trusted=True):
    h, w = frame.shape[:2]
    colors = {"move": (80, 220, 80), "click": (0, 200, 255), "drag": (0, 140, 255),
              "right click": (255, 120, 0), "scroll": (255, 0, 200), "swipe": (0, 220, 220),
              "fist (hold)": (180, 180, 180), "paused": (0, 0, 255), "no hand": (120, 120, 120),
              "back of hand": (120, 120, 120)}
    color = colors.get(engine.mode, (255, 255, 255))
    if engine.cfg.absolute:
        x0, y0, x1, y1 = engine.region(w / h)
        cv2.rectangle(frame, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (90, 90, 90), 1)
    if lms:
        pts = [(int(x * w), int(y * h)) for x, y in lms]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (230, 230, 230), 2)
        for p in pts:
            cv2.circle(frame, p, 3, (60, 60, 230), -1)
        palm = (sum(pts[i][0] for i in PALM) // len(PALM), sum(pts[i][1] for i in PALM) // len(PALM))
        cv2.circle(frame, palm, 9, color, 2)
        cv2.line(frame, pts[THUMB_TIP], pts[INDEX_TIP], (0, 200, 255) if engine.left else (100, 100, 100), 1)
    cv2.rectangle(frame, (0, 0), (w, 34), (25, 25, 25), -1)
    cv2.putText(frame, engine.mode.upper(), (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    if time.monotonic() < engine.flash_until:
        (tw, _), _ = cv2.getTextSize(engine.flash, cv2.FONT_HERSHEY_SIMPLEX, 1.4, 3)
        cv2.putText(frame, engine.flash, ((w - tw) // 2, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    if engine.mode == "scroll" and engine.tilt_rest is not None:
        txt = f"tilt {engine.tilt:+.0f}" if engine.tilt else "tilt to scroll"
        cv2.putText(frame, txt, (w // 2 - 90, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    elif engine.metrics:
        txt = f"pinch L {engine.metrics['left']:.2f}  R {engine.metrics['right']:.2f}"
        cv2.putText(frame, txt, (w // 2 - 90, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.putText(frame, f"{fps:4.0f} fps", (w - 85, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    ver = f"v{VERSION}"
    (tw, _), _ = cv2.getTextSize(ver, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.putText(frame, ver, (w - 100 - tw, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 140, 140), 1)
    if not trusted:
        cv2.rectangle(frame, (0, 34), (w, 84), (0, 0, 170), -1)
        cv2.putText(frame, "Cursor control is OFF: allow Hand Mouse in", (10, 54),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(frame, "Settings > Privacy & Security > Accessibility", (10, 76),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    keys = "q quit   p pause   s settings" if os.environ.get("HANDMOUSE_SETTINGS") else "q quit   p pause"
    cv2.putText(frame, keys, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Control the mouse with hand gestures via the webcam.")
    p.add_argument("--version", action="version", version=f"Hand Mouse {VERSION}")
    p.add_argument("--camera", default="0", help="camera index (or video file path); default 0")
    p.add_argument("--absolute", action="store_true",
                   help="hand position maps directly to screen position (default: relative, "
                        "like a trackpad; make a fist to re-center)")
    p.add_argument("--reach", type=float, default=0.45,
                   help="fraction of the camera width you sweep to cross the screen (default 0.45)")
    p.add_argument("--speed", type=float, default=0.65, help="cursor speed multiplier (relative mode), default 0.65")
    p.add_argument("--smoothing", type=float, default=1.0, help="higher = smoother but laggier")
    p.add_argument("--pinch-on", type=float, default=0.28, help="pinch press threshold")
    p.add_argument("--pinch-off", type=float, default=0.40, help="pinch release threshold")
    p.add_argument("--drag-threshold", type=float, default=25, help="px to move while pinched before a drag starts")
    p.add_argument("--release-freeze", type=float, default=0.15, help="seconds the cursor holds after a click")
    p.add_argument("--scroll-speed", type=float, default=3500, help="scroll px per full frame height of motion")
    p.add_argument("--invert-scroll", action="store_true", help="reverse scroll direction")
    p.add_argument("--tilt-scroll-speed", type=float, default=1200,
                   help="scroll px/s with the peace sign tilted 30 degrees (default 1200); "
                        "tilting further goes faster")
    p.add_argument("--no-tilt", action="store_true",
                   help="tilting the hand doesn't scroll or swipe; only moving it does")
    p.add_argument("--swipe-action", choices=("desktops", "browser", "off"), default="desktops",
                   help="what a peace-sign sideways flick does: switch desktops (Ctrl+arrows, default), "
                        "browser back/forward (Cmd+[ / ]), or nothing")
    p.add_argument("--no-three-finger-swipe", action="store_true",
                   help="turn off the three-finger flick that switches desktops")
    p.add_argument("--allow-back-of-hand", action="store_true",
                   help="track the hand even when its back faces the camera (default: only the palm side)")
    p.add_argument("--no-preview", action="store_true", help="don't show the camera window (Ctrl+C to quit)")
    p.add_argument("--dry-run", action="store_true", help="track and print actions, don't move the mouse")
    p.add_argument("--model", help=argparse.SUPPRESS)
    p.add_argument("--app", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None):
    global APP_MODE
    cfg = parse_args(argv)
    APP_MODE = cfg.app
    on_mac = platform.system() == "Darwin"
    if APP_MODE and on_mac:
        setup_app_identity()
    if cfg.dry_run or not on_mac:
        if not on_mac and not cfg.dry_run:
            print("Not on macOS: running in dry-run mode (mouse is not moved).")
        mouse = DryRunMouse(verbose=True)
        trusted = True
    else:
        mouse = SmoothMouse(MacMouse())
        trusted = accessibility_trusted(prompt=True)   # shows the system prompt if needed
        if not trusted:
            print("!! Accessibility permission is missing, so the cursor won't move yet.\n"
                  "   System Settings > Privacy & Security > Accessibility", file=sys.stderr)

    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=ensure_model(cfg.model)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    cap = open_camera(cfg.camera)
    engine = GestureEngine(mouse, cfg)
    atexit.register(engine.release_all)   # also covers Cmd+Q, which exits without unwinding
    win = "Hand Mouse"
    t0, last_ts, fps, prev_t, fails = time.monotonic(), -1, 0.0, time.monotonic(), 0
    last_trust_check, window_seen = time.monotonic(), False
    print(f"Hand Mouse {VERSION}")
    print(__doc__)

    try:
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            while True:
                ok, frame = cap.read()
                if not ok:
                    fails += 1
                    if fails > 30 or not str(cfg.camera).isdigit():
                        if str(cfg.camera).isdigit():
                            alert("The camera stopped delivering video.", pane="camera")
                        break
                    time.sleep(0.03)
                    continue
                fails = 0
                frame = cv2.flip(frame, 1)   # mirror: moving right moves the cursor right
                now = time.monotonic()
                ts = max(int((now - t0) * 1000), last_ts + 1)
                last_ts = ts
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                lms = [(l.x, l.y) for l in result.hand_landmarks[0]] if result.hand_landmarks else None
                handed = result.handedness[0][0].category_name if lms and result.handedness else None
                world = ([(l.x, l.y, l.z) for l in result.hand_world_landmarks[0]]
                         if lms and result.hand_world_landmarks else None)
                engine.update(lms, frame.shape[1] / frame.shape[0], now, handed, world)

                if not trusted and now - last_trust_check > 2:   # pick up a newly granted permission
                    trusted, last_trust_check = accessibility_trusted(), now
                fps = 0.9 * fps + 0.1 / max(now - prev_t, 1e-3)
                prev_t = now
                if not cfg.no_preview:
                    draw_hud(frame, engine, lms, fps, trusted)
                    cv2.imshow(win, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break
                    if key in (ord("p"), ord(" ")):
                        engine.toggle_pause()
                    if key == ord("s") and os.environ.get("HANDMOUSE_SETTINGS"):
                        subprocess.Popen(["open", "-e", os.environ["HANDMOUSE_SETTINGS"]])
                    # Closing the window with its red button quits.
                    try:
                        visible = cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE)
                    except cv2.error:
                        visible = 0 if window_seen else 1
                    if visible >= 1:
                        window_seen = True
                    elif window_seen:
                        break
    except KeyboardInterrupt:
        pass
    finally:
        engine.release_all()   # never leave the mouse button stuck down
        cap.release()
        cv2.destroyAllWindows()
    return engine


if __name__ == "__main__":
    main()
