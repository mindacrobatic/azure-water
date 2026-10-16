#version 330

// Composite: HDR + bloom, ACES tonemap, vignette, dither, gamma.

in vec2 v_uv;
out vec4 f_color;
uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_exposure;
uniform float u_bloom_strength;
uniform vec2 u_screen;
uniform float u_time;

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    c += texture(u_bloom, v_uv).rgb * u_bloom_strength;

    c *= u_exposure;
    c = aces(c);

    float v = distance(v_uv, vec2(0.5));
    c *= mix(1.0, smoothstep(0.95, 0.35, v), 0.35);

    c += (hash12(v_uv * u_screen + u_time) - 0.5) / 512.0;
    c = pow(max(c, 0.0), vec3(1.0 / 2.2));

    f_color = vec4(c, 1.0);
}
