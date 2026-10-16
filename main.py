"""Azure Water — entry point: GLFW window, input handling, main loop.

Run:  .venv/bin/python main.py
Keys (German Mac layout): mouse drag = orbit, wheel = zoom, WASD = pan,
      Q/E = up/down, 1/2/3 = wave preset,
      , = calmer sun / . = higher sun (ü also works),
      - = less exposure / + = more exposure (´ also works),
      SPACE pauses time, P screenshot, R reset, ESC quit.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import glfw
import moderngl
import numpy as np
from PIL import Image

from water.renderer import PRESETS, Renderer

WAVE_CHOICES = {"calm": 0, "breeze": 1, "storm": 2}


def parse_size(text: str):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("size must be WxH, e.g. 1280x800")


def save_screenshot(ctx: moderngl.Context, size, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    data = ctx.screen.read(components=3)
    img = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)[::-1]
    Image.fromarray(img).save(path)
    return path


class App:
    def __init__(self, args):
        self.args = args
        if not glfw.init():
            raise RuntimeError("glfw init failed")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.SAMPLES, 0)

        self.win = glfw.create_window(args.size[0], args.size[1], "Azure Water", None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("could not create window")
        glfw.make_context_current(self.win)
        glfw.swap_interval(1 if args.vsync else 0)

        self.ctx = moderngl.create_context()
        print(f"GL {self.ctx.info['GL_VERSION']} | {self.ctx.info['GL_RENDERER']}")

        fw, fh = glfw.get_framebuffer_size(self.win)
        self.renderer = Renderer(
            self.ctx, (fw, fh),
            sun_az=args.sun_az, sun_elev=args.sun_elev,
            preset=args.waves, exposure=args.exposure,
        )

        self.keys: set[int] = set()
        self.drag = False
        self.last_cursor = (0.0, 0.0)
        self.shot_requested = False
        self.frames = 0
        self.fps = 0.0
        self._title_t = 0.0
        self._fps_frames = 0
        self._fps_t = time.perf_counter()

        win = self.win
        glfw.set_key_callback(win, self.on_key)
        glfw.set_mouse_button_callback(win, self.on_mouse_button)
        glfw.set_cursor_pos_callback(win, self.on_cursor)
        glfw.set_scroll_callback(win, self.on_scroll)

    # ----------------------------------------------------------- input
    def on_key(self, win, key, scancode, action, mods):
        r = self.renderer
        if action in (glfw.PRESS, glfw.REPEAT):
            self.keys.add(key)
        if action == glfw.RELEASE:
            self.keys.discard(key)
        if action != glfw.PRESS:
            return

        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(win, True)
        elif key == glfw.KEY_R:
            r.camera.target[:] = (0.0, 0.6, 0.0)
            r.camera.az = r.sun_az - 6.0
            r.camera.el = -3.0
            r.camera.radius = 60.0
        elif key == glfw.KEY_P:
            self.shot_requested = True
        elif key == glfw.KEY_SPACE:
            r.paused = not r.paused
        elif key in (glfw.KEY_1, glfw.KEY_2, glfw.KEY_3):
            r.set_preset(key - glfw.KEY_1)
        # GLFW key codes follow US physical key positions. German Mac labels:
        # ü = LEFT_BRACKET, + = RIGHT_BRACKET, - = SLASH, ß = MINUS, ´ = EQUAL.
        elif key in (glfw.KEY_COMMA, glfw.KEY_LEFT_BRACKET):       # , or ü
            r.change_sun(-1.2)
        elif key == glfw.KEY_PERIOD:                               # .
            r.change_sun(1.2)
        elif key in (glfw.KEY_SLASH, glfw.KEY_MINUS):              # - or ß
            r.adjust_exposure(0.85)
        elif key in (glfw.KEY_RIGHT_BRACKET, glfw.KEY_EQUAL):      # + or ´
            r.adjust_exposure(1.18)

    def on_mouse_button(self, win, button, action, mods):
        if button == glfw.MOUSE_BUTTON_LEFT:
            self.drag = action == glfw.PRESS
            if self.drag:
                self.last_cursor = glfw.get_cursor_pos(win)

    def on_cursor(self, win, x, y):
        if self.drag:
            dx = x - self.last_cursor[0]
            dy = y - self.last_cursor[1]
            self.renderer.camera.orbit(dx, dy)
        self.last_cursor = (x, y)

    def on_scroll(self, win, xoff, yoff):
        self.renderer.camera.zoom(yoff)

    def apply_input(self, dt: float) -> None:
        k, cam = self.keys, self.renderer.camera
        boost = 4.0 if (glfw.KEY_LEFT_SHIFT in k or glfw.KEY_RIGHT_SHIFT in k) else 1.0
        forward = int(glfw.KEY_W in k) - int(glfw.KEY_S in k)
        strafe = int(glfw.KEY_D in k) - int(glfw.KEY_A in k)
        up = int(glfw.KEY_E in k) - int(glfw.KEY_Q in k)
        if forward or strafe or up:
            cam.pan(forward * boost, strafe * boost, up * boost)

    # ------------------------------------------------------------ loop
    def run(self) -> None:
        args = self.args
        r = self.renderer
        fixed = args.frames is not None
        last = time.perf_counter()

        while not glfw.window_should_close(self.win):
            glfw.poll_events()
            fw, fh = glfw.get_framebuffer_size(self.win)
            if min(fw, fh) > 0 and (fw, fh) != r.size:
                r.resize((fw, fh))

            now = time.perf_counter()
            dt = 1.0 / 60.0 if fixed else min(0.1, now - last)
            last = now

            if not fixed:
                self.apply_input(dt)
            r.update(dt)
            r.render()

            shot_now = self.shot_requested or (fixed and self.frames == args.frames - 1)
            if shot_now:
                self.shot_requested = False
                path = args.shot or f"screenshots/azure_{time.strftime('%Y%m%d_%H%M%S')}.png"
                saved = save_screenshot(self.ctx, r.size, path)
                print(f"screenshot: {saved}")

            glfw.swap_buffers(self.win)
            self.frames += 1

            self._fps_frames += 1
            if now - self._fps_t > 0.5:
                self.fps = self._fps_frames / (now - self._fps_t)
                self._fps_frames = 0
                self._fps_t = now
                glfw.set_window_title(
                    self.win,
                    f"Azure Water | {PRESETS[r.preset_index]['name']} | "
                    f"sun {r.sun_elev:.1f} deg | exp {r.exposure:.2f} | {self.fps:.0f} fps",
                )

            if fixed and self.frames >= args.frames:
                break

        glfw.terminate()


def main() -> None:
    p = argparse.ArgumentParser(description="Azure Water — real-time ocean with planar reflections")
    p.add_argument("--size", type=parse_size, default=(1280, 800), help="window size, e.g. 1280x800")
    p.add_argument("--shot", type=str, default=None, help="screenshot path (with --frames for headless-ish runs)")
    p.add_argument("--frames", type=int, default=None, help="render N frames, save --shot, then exit")
    p.add_argument("--sun-az", type=float, default=200.0, dest="sun_az")
    p.add_argument("--sun-elev", type=float, default=5.0, dest="sun_elev")
    p.add_argument("--waves", choices=sorted(WAVE_CHOICES), default="breeze")
    p.add_argument("--exposure", type=float, default=1.0)
    p.add_argument("--no-vsync", action="store_false", dest="vsync")
    args = p.parse_args()
    args.waves = WAVE_CHOICES[args.waves]

    App(args).run()


if __name__ == "__main__":
    main()
