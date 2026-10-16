#version 330

in vec2 v_uv;
out vec4 f_color;
uniform sampler2D u_hdr;
uniform float u_threshold;

void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float w = max(lum - u_threshold, 0.0);
    w = w * w / (w + 0.35);                 // soft knee
    f_color = vec4(c * (w / max(lum, 1e-4)), 1.0);
}
