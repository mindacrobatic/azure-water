#version 330

in vec2 in_pos;
out vec2 v_uv;   // 0..1 for texture sampling
out vec2 v_ndc;  // -1..1 for ray reconstruction

void main() {
    v_ndc = in_pos;
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
