#version 330

// Water surface: Fresnel-mixed planar reflection and refracted scene,
// Beer-Lambert absorption, GGX sun specular, crest foam, horizon haze.

in vec3 v_world;
in vec3 v_normal;
in float v_height;
in float v_dist;
out vec4 f_color;

uniform sampler2D u_scene;        // scene color (below water)
uniform sampler2D u_scene_depth;  // scene depth texture
uniform sampler2D u_refl;         // half-res planar reflection

uniform vec2 u_screen;            // framebuffer size
uniform vec3 u_cam_pos;
uniform float u_near;
uniform float u_far;

uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform float u_sun_intensity;

uniform vec3 u_deep_color;        // scattering target colour
uniform vec3 u_absorb;            // per-channel absorption (1/m)

uniform float u_foam_threshold;
uniform float u_foam_amount;

uniform float u_detail_amp;
uniform float u_roughness;
uniform float u_refl_distort;
uniform float u_refract_distort;
uniform float u_fog_k;
uniform float u_fog_end;
uniform float u_time;
uniform vec2 u_wind_dir;

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash12(i);
    float b = hash12(i + vec2(1.0, 0.0));
    float c = hash12(i + vec2(0.0, 1.0));
    float d = hash12(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

// 4-tap soft sample; spread grows with distance for hazier far reflections.
vec3 tap(sampler2D tex, vec2 uv, float spread) {
    vec2 s = vec2(0.75, 0.31) * spread / vec2(textureSize(tex, 0));
    vec3 c = texture(tex, uv).rgb * 0.5;
    c += texture(tex, uv + s).rgb * 0.25;
    c += texture(tex, uv - s).rgb * 0.25;
    return c;
}

float linear_depth(float z01) {
    float zn = z01 * 2.0 - 1.0;
    return (2.0 * u_near * u_far) / (u_far + u_near - zn * (u_far - u_near));
}

void micro(inout vec2 d, vec2 p, vec2 dir, float k, float amp, float speed) {
    d += dir * (amp * k * cos(k * dot(p, dir) + u_time * speed));
}

vec3 detail_normal(vec2 p, float dist) {
    vec2 w = normalize(u_wind_dir);
    vec2 w2 = vec2(-w.y, w.x);
    vec2 d = vec2(0.0);
    float wf = 1.0 / (1.0 + dist * 0.014);
    float wc = 1.0 / (1.0 + dist * 0.0022);

    // fine ripples
    micro(d, p, normalize(w * 1.0 + w2 * 0.55), 4.5, 0.015 * wf, 6.5);
    micro(d, p, normalize(w * 0.35 - w2 * 1.0), 6.5, 0.012 * wf, 8.5);
    micro(d, p, normalize(-w * 0.80 + w2 * 0.40), 3.2, 0.016 * wf, 4.8);
    // coarse chop
    micro(d, p, normalize(w * 0.90 + w2 * 0.15), 0.75, 0.10 * wc, 2.0);
    micro(d, p, normalize(w * 0.30 - w2 * 0.90), 1.15, 0.08 * wc, 2.6);
    micro(d, p, normalize(-w * 0.50 - w2 * 0.60), 0.55, 0.09 * wc, 1.6);

    return normalize(vec3(-d.x, 1.0, -d.y));
}

void main() {
    vec3 geoN = normalize(v_normal);
    vec3 nd = detail_normal(v_world.xz, v_dist);
    vec3 N = normalize(geoN + vec3(nd.x, 0.0, nd.z) * u_detail_amp);

    vec3 V = normalize(u_cam_pos - v_world);
    float NoV = clamp(dot(N, V), 1e-3, 1.0);
    float fres = 0.02 + 0.98 * pow(1.0 - NoV, 5.0);

    vec2 uv = gl_FragCoord.xy / u_screen;
    vec2 ndxz = vec2(N.x, N.z);

    // ---- reflection -------------------------------------------------
    // Slope-driven screen-space displacement: grazing rays are far more
    // sensitive to tilt, which keeps the distant sea from turning to glass.
    vec3 R = reflect(-V, N);
    float sens = clamp(0.15 / max(R.y, 0.02), 1.0, 8.0);
    vec2 ruv = clamp(uv + ndxz * u_refl_distort * sens, vec2(0.001), vec2(0.999));
    // Grazing reflections are footprint-compressed; widen the tap so the
    // ribbon of horizon detail smears into haze instead of streaks.
    vec3 refl = tap(u_refl, ruv, 1.0 + v_dist * 0.02 + 2.5 * (sens - 1.0));

    // ---- refraction + absorption ------------------------------------
    vec2 tuv = clamp(uv + ndxz * u_refract_distort / (1.0 + v_dist * 0.06),
                     vec2(0.001), vec2(0.999));
    float fragLD = linear_depth(gl_FragCoord.z);
    float sampLD = linear_depth(texture(u_scene_depth, tuv).r);
    if (sampLD < fragLD || sampLD > u_far * 0.98) {   // invalid refracted sample
        tuv = uv;
        sampLD = linear_depth(texture(u_scene_depth, uv).r);
    }
    vec3 scene_col = texture(u_scene, tuv).rgb;
    float thickness = clamp(sampLD - fragLD, 0.0, 60.0);
    vec3 trans = exp(-u_absorb * thickness);
    vec3 below = scene_col * trans + u_deep_color * (1.0 - trans);

    vec3 col = mix(below, refl, fres);

    // ---- sun specular (GGX) -----------------------------------------
    vec3 L = u_sun_dir;
    vec3 H = normalize(L + V);
    float NoL = clamp(dot(N, L), 0.0, 1.0);
    float NoH = clamp(dot(N, H), 0.0, 1.0);
    float VoH = clamp(dot(V, H), 0.0, 1.0);
    float a = max(u_roughness * u_roughness, 1e-4);
    float a2 = a * a;
    float den = NoH * NoH * (a2 - 1.0) + 1.0;
    float D = a2 / (3.14159265 * den * den);
    float kSpec = a * 0.5;
    float G = (NoL / (NoL * (1.0 - kSpec) + kSpec)) *
              (NoV / (NoV * (1.0 - kSpec) + kSpec));
    float Fs = 0.02 + 0.98 * pow(1.0 - VoH, 5.0);
    vec3 spec = u_sun_color * u_sun_intensity * (D * G * Fs / (4.0 * NoL * NoV + 1e-4)) * NoL;
    spec = min(spec, vec3(80.0));
    col += spec;

    // ---- foam --------------------------------------------------------
    // Coarsen the foam pattern with distance: the world-space noise would
    // alias into a continuous crust at grazing angles.
    float fscale = 1.0 + v_dist * 0.02;
    float fn = vnoise(v_world.xz * 1.7 / fscale + vec2(u_time * 0.12, -u_time * 0.08));
    float fn2 = vnoise(v_world.xz * 4.1 / fscale - vec2(u_time * 0.20, u_time * 0.05));
    float fnoise = fn * 0.6 + fn2 * 0.4;
    float crest = smoothstep(u_foam_threshold, u_foam_threshold + 0.38,
                             v_height + (fnoise - 0.5) * 0.55);
    // Fade foam with distance: the high-frequency noise pattern aliases into
    // streaks at grazing angles far away.
    crest *= 1.0 - 0.65 * smoothstep(180.0, 520.0, v_dist);
    vec3 foam_col = vec3(0.82, 0.90, 0.96) * (0.55 + 0.45 * u_sun_color);
    col = mix(col, foam_col, crest * u_foam_amount);

    // Subsurface glow in backlit wave crests.
    float back = max(dot(V, -u_sun_dir), 0.0);
    float crest_glow = smoothstep(0.35, 1.0, v_height) * pow(back, 2.0);
    col += u_sun_color * u_sun_intensity * 0.22 * crest_glow;

    // ---- horizon haze (blend towards the sky it reflects) -----------
    vec3 sky_ref = tap(u_refl, uv, 1.0 + v_dist * 0.02);
    float fog = 1.0 - exp(-pow(v_dist * u_fog_k, 1.5));
    fog = max(fog, smoothstep(u_fog_end * 0.70, u_fog_end, v_dist));
    col = mix(col, sky_ref, clamp(fog, 0.0, 1.0));

    f_color = vec4(col, 1.0);
}
