# Azure Water

Real-time ocean in Python — a Gerstner-wave sea with planar reflections, a procedural sky, bloom and ACES tone mapping, rendered with [ModernGL](https://moderngl.readthedocs.io/) and GLFW.

![Azure Water at sunset](screenshots/check_breeze.png)

## Features

- **Gerstner waves** on a radially mapped grid (dense near the camera), 8 wave components with analytic normals, distance LOD fade and near-camera flattening so the surface never clips through the view
- **Planar reflection** rendered from a mirrored camera at half resolution
- **Refraction** of a scene buffer (sky + seabed) with Beer–Lambert absorption and depth-based validity checks
- **GGX sun specular** with slope-driven reflection distortion that stays correct at grazing angles
- **Crest foam** with wind-shifted noise, distance-coarsened to avoid aliasing
- **Procedural sky**: gradient, sun disc/glow, fbm clouds, mountain silhouettes — also used as the reflection source
- **Sandy seabed** with animated caustics, seen through the water volume
- **Post-processing**: bright-pass + separable blur bloom, ACES tone map, vignette, dither, gamma
- Three wave presets and live sun/exposure controls, shown in the window title

## Requirements

- Python 3.10+ (developed on 3.14)
- A GPU/driver with OpenGL 3.3 core (macOS uses the Metal-backed 4.1 core profile)
- Packages from `requirements.txt`: moderngl, glfw, numpy, Pillow

## Setup

```sh
cd azure-water
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```sh
.venv/bin/python main.py
```

### Command-line flags

| Flag | Default | Description |
|---|---|---|
| `--size WxH` | `1280x800` | Window size (Retina scales the framebuffer 2×) |
| `--waves {calm,breeze,storm}` | `breeze` | Starting wave preset |
| `--sun-elev DEG` | `5` | Sun elevation (low = sunset, high = noon) |
| `--sun-az DEG` | `200` | Sun azimuth |
| `--exposure F` | `1.0` | Starting exposure |
| `--no-vsync` | off | Disable vertical sync (uncapped FPS) |
| `--frames N` | — | Render N fixed frames, then exit |
| `--shot PATH` | — | Screenshot path (with `--frames` for scripted captures) |

Example — a scripted storm capture:

```sh
.venv/bin/python main.py --waves storm --frames 60 --shot screenshots/storm.png
```

## Controls

The bindings follow the **German Mac keyboard** (GLFW reports keys by US physical position, so labels differ from a US layout):

| Action | Key |
|---|---|
| Orbit / zoom | mouse drag / wheel |
| Pan | `W` `A` `S` `D` (hold Shift = faster) |
| Move up / down | `E` / `Q` |
| Wave preset Calm / Breeze / Storm | `1` / `2` / `3` |
| Calmer sun / higher sun | `,` / `.` (also `ü`) |
| Less / more exposure | `-` / `+` (also `ß` / `´`) |
| Pause time | `SPACE` |
| Screenshot | `P` (saves to `screenshots/azure_<timestamp>.png`) |
| Reset camera | `R` |
| Quit | `ESC` |

On a US layout the same physical keys read as `,`/`[` and `.` for the sun and `/`/`-` and `]`/`=` for exposure.

## Presets

| Preset | Character |
|---|---|
| `calm` | Glassy swell, no foam |
| `breeze` | Moderate swell with scattered whitecaps (default) |
| `storm` | Large cross seas, heavy crest foam |

Preset parameters (amplitude, steepness, foam, detail, roughness, directional spread) live in `PRESETS` in `water/renderer.py`.

## How it renders

Each frame, in order:

1. **Reflection pass** — the procedural sky is rendered into a half-resolution buffer using the camera mirrored across the water plane
2. **Scene pass** — sky + seabed (with caustics) into scene color + depth textures
3. **Water pass** — the displaced water grid shades a Fresnel mix of the reflected and refracted scene, adds absorption, sun specular and foam
4. **Bloom** — bright-pass at half resolution, then horizontal + vertical blur
5. **Composite** — HDR + bloom, ACES tone map, vignette, dither, gamma

## Debugging

Set `AZURE_DEBUG` to inspect intermediate buffers instead of the final image:

```sh
AZURE_DEBUG=refl  .venv/bin/python main.py   # planar reflection buffer
AZURE_DEBUG=scene .venv/bin/python main.py   # sky + seabed
AZURE_DEBUG=hdr   .venv/bin/python main.py   # pre-bloom HDR
```

Add `--frames N --shot path.png` if you want to capture the debug view instead of watching it live.

## Layout

```
main.py                window, input handling, main loop, screenshot saving
water/camera.py        matrix helpers and the orbit camera
water/renderer.py      render passes, presets, palettes, wave parameters
water/shaders/         GLSL 330 vertex/fragment shaders
screenshots/           captures from the P key or --shot
```
