#version 330

// Sandy seabed with animated caustics, seen through the water volume.

in vec3 v_world;
out vec4 f_color;

uniform vec3 u_cam_pos;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform vec3 u_sand_a;
uniform vec3 u_sand_b;
uniform vec3 u_deep_color;
uniform float u_time;
uniform float u_caustic;

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

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * vnoise(p);
        p = p * 2.03 + vec2(11.3, 5.7);
        a *= 0.5;
    }
    return v;
}

float caustics(vec2 p, float t) {
    vec2 q = p * 1.4;
    float a = sin(q.x * 1.13 + q.y * 0.31 + t * 0.9 + sin(q.y * 0.9 + t * 0.4) * 0.8);
    float b = sin(q.y * 1.27 - q.x * 0.57 - t * 0.7 + sin(q.x * 1.1 - t * 0.5) * 0.8);
    float c1 = pow(clamp(0.5 * a * b + 0.5, 0.0, 1.0), 3.0);

    vec2 q2 = p * 0.42 + vec2(31.0, 7.0);
    float a2 = sin(q2.x * 1.1 + t * 0.55 + sin(q2.y * 0.7 - t * 0.3));
    float b2 = sin(q2.y * 1.33 - t * 0.45 + sin(q2.x * 0.8 + t * 0.35));
    float c2 = pow(clamp(0.5 * a2 * b2 + 0.5, 0.0, 1.0), 3.5);

    vec2 q3 = p * 3.1 + vec2(3.7, 19.0);
    float c3 = pow(clamp(0.5 * sin(q3.x + t * 1.3) * sin(q3.y * 0.9 - t * 1.1) + 0.5, 0.0, 1.0), 4.0);

    return (c1 + 0.5 * c2 + 0.35 * c3) / 1.85;
}

void main() {
    vec2 p = v_world.xz;

    float rip = fbm(p * 0.22);
    float grain = vnoise(p * 1.6);
    vec3 sand = mix(u_sand_a, u_sand_b, clamp(rip * 1.2 + 0.25 * grain - 0.25, 0.0, 1.0));

    float ca = caustics(p, u_time) * u_caustic;
    vec3 col = sand * (0.30 + 0.85 * ca);

    float sun_up = clamp(u_sun_dir.y, 0.0, 1.0);
    col *= (vec3(0.22, 0.26, 0.32) + u_sun_color * sun_up * 1.15);

    // Distance haze towards the deep colour (water absorption adds more).
    float d = distance(v_world, u_cam_pos);
    col = mix(col, u_deep_color * 0.65, 1.0 - exp(-d * 0.014));

    f_color = vec4(col, 1.0);
}
