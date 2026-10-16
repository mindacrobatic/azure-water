"""Renders the ocean scene: planar reflection, scene depth, water surface,
bloom and tone-mapped composite."""
from __future__ import annotations

import math
import os
from pathlib import Path

import moderngl
import numpy as np

from .camera import OrbitCamera, dir_from_angles, perspective, reflect_y

SHADER_DIR = Path(__file__).parent / "shaders"

NUM_WAVES = 8
G = 9.81
LAMBDAS = np.array([64.0, 41.0, 26.0, 16.5, 10.5, 6.7, 4.3, 2.8])

PRESETS = [
    dict(name="Calm", amp=0.30, steep=0.55, foam=0.00, detail=0.55, rough=0.045, spread=14.0),
    dict(name="Breeze", amp=0.95, steep=0.85, foam=0.45, detail=1.00, rough=0.075, spread=26.0),
    dict(name="Storm", amp=2.30, steep=1.00, foam=0.90, detail=2.20, rough=0.095, spread=42.0),
]


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def _mix(a, b, t: float):
    return np.array(a, dtype=np.float64) + (np.array(b, dtype=np.float64) - np.array(a)) * t


class Renderer:
    def __init__(self, ctx: moderngl.Context, size, sun_az=200.0, sun_elev=5.0,
                 preset=1, exposure=1.0, wind_az=None):
        self.ctx = ctx
        self.size = (int(size[0]), int(size[1]))
        self.water_level = 0.0
        self.time = 0.0
        self.cloud_offset = np.zeros(2, dtype=np.float32)
        self.paused = False

        self.sun_az = float(sun_az)
        self.sun_elev = float(sun_elev)
        self.wind_az = float(sun_az - 3.0) if wind_az is None else float(wind_az)
        self.exposure = float(exposure)
        self.preset_index = int(preset)

        self.camera = OrbitCamera(az=self.sun_az - 6.0, el=-3.0, radius=60.0)
        self.fov = 45.0
        self.near = 0.2
        self.far = 5000.0

        self.prog_sky = self._program("quad.vert", "sky.frag")
        self.prog_seabed = self._program("seabed.vert", "seabed.frag")
        self.prog_water = self._program("water.vert", "water.frag")
        self.prog_bright = self._program("quad.vert", "brightpass.frag")
        self.prog_blur = self._program("quad.vert", "blur.frag")
        self.prog_comp = self._program("quad.vert", "composite.frag")

        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1], dtype="f4"))
        self.vaos_quad = {
            name: ctx.vertex_array(prog, [(quad, "2f", "in_pos")])
            for name, prog in [("sky", self.prog_sky), ("bright", self.prog_bright),
                               ("blur", self.prog_blur), ("comp", self.prog_comp)]
        }

        self._build_geometry()
        self._create_targets(self.size)
        self.set_preset(self.preset_index)
        self._update_palette()

    # ------------------------------------------------------------------
    def _program(self, *names: str) -> moderngl.Program:
        sources = {Path(n).suffix: (SHADER_DIR / n).read_text() for n in names}
        return self.ctx.program(vertex_shader=sources[".vert"], fragment_shader=sources[".frag"])

    def _build_geometry(self) -> None:
        # Water grid: radially mapped so it is dense near the camera.
        n, extent, power = 512, 600.0, 1.6
        u = np.linspace(-1.0, 1.0, n + 1)
        x = np.sign(u) * np.abs(u) ** power * extent
        sx, sz = np.meshgrid(x, x, indexing="ij")
        xy = np.stack([sx, sz], axis=-1).reshape(-1, 2).astype("f4")

        i = np.arange(n * n).reshape(n, n)
        a = n + 1
        tris = np.stack([i, i + a, i + 1, i + 1, i + a, i + a + 1], axis=-1).reshape(-1).astype("u4")

        vbo = self.ctx.buffer(xy)
        ibo = self.ctx.buffer(tris)
        self.water_vao = self.ctx.vertex_array(
            self.prog_water, [(vbo, "2f", "in_pos")], index_buffer=ibo, index_element_size=4
        )

        # Seabed: flat plane below the water.
        m = 32
        su = np.linspace(-1500.0, 1500.0, m + 1)
        bx, bz = np.meshgrid(su, su, indexing="ij")
        by = np.full_like(bx, -4.0)
        seabed = np.stack([bx, by, bz], axis=-1).reshape(-1, 3).astype("f4")
        si = np.arange(m * m).reshape(m, m)
        sa = m + 1
        stris = np.stack([si, si + sa, si + 1, si + 1, si + sa, si + sa + 1], axis=-1).reshape(-1).astype("u4")
        self.seabed_vao = self.ctx.vertex_array(
            self.prog_seabed,
            [(self.ctx.buffer(seabed), "3f", "in_pos")],
            index_buffer=self.ctx.buffer(stris), index_element_size=4,
        )

    def _create_targets(self, size) -> None:
        w, h = size
        ctx = self.ctx
        rw, rh = max(2, w // 2), max(2, h // 2)
        bw, bh = max(2, w // 2), max(2, h // 2)

        self.refl_tex = ctx.texture((rw, rh), 4, dtype="f2")
        self.refl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.fbo_refl = ctx.framebuffer(color_attachments=[self.refl_tex])

        self.scene_tex = ctx.texture((w, h), 4, dtype="f2")
        self.scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.scene_depth = ctx.depth_texture((w, h))
        self.scene_depth.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.fbo_scene = ctx.framebuffer(color_attachments=[self.scene_tex],
                                         depth_attachment=self.scene_depth)

        self.hdr_tex = ctx.texture((w, h), 4, dtype="f2")
        self.hdr_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.hdr_depth = ctx.depth_texture((w, h))
        self.hdr_depth.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.fbo_hdr = ctx.framebuffer(color_attachments=[self.hdr_tex],
                                       depth_attachment=self.hdr_depth)

        self.bloom_tex = [ctx.texture((bw, bh), 4, dtype="f2") for _ in range(2)]
        for t in self.bloom_tex:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.fbo_bloom = [ctx.framebuffer(color_attachments=[t]) for t in self.bloom_tex]

    def resize(self, size) -> None:
        size = (int(size[0]), int(size[1]))
        if size == self.size or min(size) < 4:
            return
        self.size = size
        for obj in (self.fbo_refl, self.fbo_scene, self.fbo_hdr, self.refl_tex,
                    self.scene_tex, self.scene_depth, self.hdr_tex, self.hdr_depth,
                    *self.bloom_tex, *self.fbo_bloom):
            obj.release()
        self._create_targets(size)

    # ------------------------------------------------------------------
    def set_preset(self, index: int) -> None:
        self.preset_index = index % len(PRESETS)
        p = PRESETS[self.preset_index]
        lams = LAMBDAS[:NUM_WAVES]
        ks = 2.0 * math.pi / lams
        amps = p["amp"] * (lams / lams[0]) ** 0.85
        angles = math.radians(self.wind_az) + np.radians(np.linspace(-p["spread"], p["spread"], NUM_WAVES))
        dirs = np.stack([np.sin(angles), np.cos(angles)], axis=1)
        omegas = np.sqrt(G * ks)
        qs = np.minimum(p["steep"] / (ks * amps * NUM_WAVES), 1.0)

        self.wave_dir = dirs.astype("f4")
        self.wave_k = ks.astype("f4")
        self.wave_amp = amps.astype("f4")
        self.wave_q = qs.astype("f4")
        self.wave_omega = omegas.astype("f4")
        self.wave_amp_total = float(amps.sum())

        # Keep the eye above the crests so the camera never ends up inside a
        # wave, where the surface slices across the view.
        self.camera.eye_min_y = max(0.35, 0.85 * self.wave_amp_total + 0.3)
        self.near_fade = float(min(12.0, max(1.5, 1.4 * self.wave_amp_total)))

        self.foam_threshold = 0.85 - 0.5 * p["foam"]
        self.foam_amount = p["foam"]
        self.detail_amp = p["detail"]
        self.roughness = p["rough"]

    def _update_palette(self) -> None:
        t = _smoothstep((self.sun_elev - 3.0) / 32.0)
        self.zenith = _mix((0.060, 0.090, 0.30), (0.135, 0.30, 0.72), t)
        self.horizon = _mix((1.20, 0.30, 0.07), (0.70, 0.82, 0.96), t)
        self.haze = _mix((0.95, 0.35, 0.10), (0.78, 0.86, 1.00), t)
        self.sun_color = _mix((1.00, 0.55, 0.24), (1.00, 0.93, 0.83), t)
        self.sun_intensity = float(_mix(1.7, 3.2, t))
        self.disc_bright = float(_mix(36.0, 20.0, t))
        self.below = self.zenith * 0.35
        self.ridge_far = self.haze * 0.25 + _mix((0.32, 0.30, 0.44), (0.42, 0.47, 0.58), t) * 0.75
        self.ridge_near = self.haze * 0.12 + _mix((0.16, 0.13, 0.22), (0.24, 0.24, 0.32), t) * 0.88
        self.deep_color = _mix((0.015, 0.075, 0.155), (0.012, 0.095, 0.20), t)
        self.absorb = np.array([0.36, 0.10, 0.055])
        self.sand_a = np.array([0.68, 0.60, 0.44])
        self.sand_b = np.array([0.42, 0.36, 0.26])
        self.sun_dir = dir_from_angles(self.sun_az, self.sun_elev)

    def change_sun(self, delta: float) -> None:
        old = self.sun_elev
        self.sun_elev = min(62.0, max(1.5, self.sun_elev + delta))
        return self.sun_elev - old

    def adjust_exposure(self, factor: float) -> None:
        self.exposure = min(9.0, max(0.05, self.exposure * factor))

    # ------------------------------------------------------------------
    def _u_mat4(self, prog: moderngl.Program, name: str, mat: np.ndarray) -> None:
        prog[name].write(mat.tobytes(order="F"))

    def _blit_to_screen(self, fbo) -> None:
        ctx = self.ctx
        w, h = self.size
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.screen.use()
        ctx.viewport = (0, 0, w, h)
        ctx.copy_framebuffer(ctx.screen, fbo)

    def _set_sky_uniforms(self, prog, inv_vp, cam_pos) -> None:
        self._u_mat4(prog, "u_inv_vp", inv_vp)
        prog["u_cam_pos"].value = tuple(map(float, cam_pos))
        prog["u_sun_dir"].value = tuple(self.sun_dir.tolist())
        prog["u_sun_color"].value = tuple(self.sun_color.tolist())
        prog["u_sun_intensity"].value = self.sun_intensity
        prog["u_disc_bright"].value = self.disc_bright
        prog["u_zenith"].value = tuple(self.zenith.tolist())
        prog["u_horizon"].value = tuple(self.horizon.tolist())
        prog["u_haze"].value = tuple(self.haze.tolist())
        prog["u_below"].value = tuple(self.below.tolist())
        prog["u_cloud_offset"].value = tuple(self.cloud_offset.tolist())
        prog["u_cloud_coverage"].value = 0.32
        prog["u_cloud_scale"].value = 0.00055
        prog["u_ridge_far"].value = tuple(self.ridge_far.tolist())
        prog["u_ridge_near"].value = tuple(self.ridge_near.tolist())

    def render(self) -> None:
        ctx = self.ctx
        cam = self.camera
        self._update_palette()
        dbg = os.environ.get("AZURE_DEBUG", "")

        w, h = self.size
        rw, rh = self.refl_tex.size

        aspect = w / h
        proj = perspective(self.fov, aspect, self.near, self.far)
        view = cam.view()
        eye = cam.eye()
        vp = proj @ view
        inv_vp = np.linalg.inv(vp)

        # --- 1. planar reflection ------------------------------------
        fbo = self.fbo_refl
        fbo.use()
        ctx.viewport = (0, 0, rw, rh)
        ctx.disable(moderngl.DEPTH_TEST)
        mir = reflect_y(self.water_level)
        eye_m = mir @ np.append(eye, 1.0)
        vp_m = proj @ (view @ mir)
        inv_vp_m = np.linalg.inv(vp_m)
        self._set_sky_uniforms(self.prog_sky, inv_vp_m, eye_m[:3])
        self.vaos_quad["sky"].render(moderngl.TRIANGLES, vertices=6)

        if dbg == "refl":
            self._blit_to_screen(self.fbo_refl)
            return

        # --- 2. scene (sky + seabed) ---------------------------------
        fbo = self.fbo_scene
        fbo.use()
        ctx.viewport = (0, 0, w, h)
        fbo.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        self._set_sky_uniforms(self.prog_sky, inv_vp, eye)
        self.vaos_quad["sky"].render(moderngl.TRIANGLES, vertices=6)

        ctx.enable(moderngl.DEPTH_TEST)
        prog = self.prog_seabed
        self._u_mat4(prog, "u_view_proj", vp)
        prog["u_cam_pos"].value = tuple(map(float, eye))
        prog["u_sun_dir"].value = tuple(self.sun_dir.tolist())
        prog["u_sun_color"].value = tuple(self.sun_color.tolist())
        prog["u_sand_a"].value = tuple(self.sand_a.tolist())
        prog["u_sand_b"].value = tuple(self.sand_b.tolist())
        prog["u_deep_color"].value = tuple(self.deep_color.tolist())
        prog["u_time"].value = self.time
        prog["u_caustic"].value = 1.3
        self.seabed_vao.render(moderngl.TRIANGLES)

        if dbg == "scene":
            self._blit_to_screen(self.fbo_scene)
            return

        # --- 3. water into the HDR buffer ----------------------------
        fbo = self.fbo_hdr
        fbo.use()
        ctx.viewport = (0, 0, w, h)
        ctx.disable(moderngl.DEPTH_TEST)
        fbo.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        ctx.copy_framebuffer(fbo, self.fbo_scene)

        ctx.enable(moderngl.DEPTH_TEST)
        prog = self.prog_water
        self._u_mat4(prog, "u_view_proj", vp)
        prog["u_center"].value = tuple(float(v) for v in np.round(cam.target[[0, 2]], 1))
        prog["u_cam_xz"].value = (float(eye[0]), float(eye[2]))
        prog["u_cam_pos"].value = tuple(map(float, eye))
        prog["u_time"].value = self.time
        prog["u_screen"].value = (float(w), float(h))
        prog["u_near"].value = self.near
        prog["u_far"].value = self.far
        prog["u_sun_dir"].value = tuple(self.sun_dir.tolist())
        prog["u_sun_color"].value = tuple(self.sun_color.tolist())
        prog["u_sun_intensity"].value = self.sun_intensity
        prog["u_deep_color"].value = tuple(self.deep_color.tolist())
        prog["u_absorb"].value = tuple(self.absorb.tolist())
        prog["u_foam_threshold"].value = self.foam_threshold
        prog["u_foam_amount"].value = self.foam_amount
        prog["u_detail_amp"].value = self.detail_amp
        prog["u_roughness"].value = self.roughness
        prog["u_refl_distort"].value = 0.017
        prog["u_refract_distort"].value = 0.008
        prog["u_fog_k"].value = 0.0045
        prog["u_fog_end"].value = 560.0
        wind = dir_from_angles(self.wind_az, 0.0)
        prog["u_wind_dir"].value = (float(wind[0]), float(wind[2]))
        prog["u_amp_total"].value = self.wave_amp_total
        prog["u_near_fade"].value = self.near_fade
        prog["u_wave_dir"].write(self.wave_dir)
        prog["u_wave_k"].write(self.wave_k)
        prog["u_wave_amp"].write(self.wave_amp)
        prog["u_wave_q"].write(self.wave_q)
        prog["u_wave_omega"].write(self.wave_omega)

        self.scene_tex.use(0)
        self.scene_depth.use(1)
        self.refl_tex.use(2)
        prog["u_scene"].value = 0
        prog["u_scene_depth"].value = 1
        prog["u_refl"].value = 2
        self.water_vao.render(moderngl.TRIANGLES)

        if dbg == "hdr":
            self._blit_to_screen(self.fbo_hdr)
            return

        # --- 4. bloom ------------------------------------------------
        ctx.disable(moderngl.DEPTH_TEST)
        bw, bh = self.bloom_tex[0].size
        ctx.viewport = (0, 0, bw, bh)
        self.hdr_tex.use(0)
        self.fbo_bloom[0].use()
        self.prog_bright["u_hdr"].value = 0
        self.prog_bright["u_threshold"].value = 2.0
        self.vaos_quad["bright"].render(moderngl.TRIANGLES, vertices=6)

        self.prog_blur["u_tex"].value = 0
        k = 1.6
        self.bloom_tex[0].use(0)
        self.fbo_bloom[1].use()
        self.prog_blur["u_dir"].value = (k / bw, 0.0)
        self.vaos_quad["blur"].render(moderngl.TRIANGLES, vertices=6)

        self.bloom_tex[1].use(0)
        self.fbo_bloom[0].use()
        self.prog_blur["u_dir"].value = (0.0, k / bh)
        self.vaos_quad["blur"].render(moderngl.TRIANGLES, vertices=6)

        # --- 5. composite to screen ----------------------------------
        ctx.screen.use()
        ctx.viewport = (0, 0, w, h)
        self.hdr_tex.use(0)
        self.bloom_tex[0].use(1)
        self.prog_comp["u_hdr"].value = 0
        self.prog_comp["u_bloom"].value = 1
        self.prog_comp["u_exposure"].value = self.exposure
        self.prog_comp["u_bloom_strength"].value = 0.35
        self.prog_comp["u_screen"].value = (float(w), float(h))
        self.prog_comp["u_time"].value = self.time
        self.vaos_quad["comp"].render(moderngl.TRIANGLES, vertices=6)

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        if not self.paused:
            self.time += dt
            self.cloud_offset += np.array([dt * 0.0016, dt * 0.0010], dtype=np.float32)
