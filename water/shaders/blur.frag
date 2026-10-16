#version 330

in vec2 v_uv;
out vec4 f_color;
uniform sampler2D u_tex;
uniform vec2 u_dir;      // texel-sized direction

void main() {
    float w[5] = float[5](0.227027, 0.194594, 0.121621, 0.054054, 0.016216);
    vec3 c = texture(u_tex, v_uv).rgb * w[0];
    for (int i = 1; i < 5; i++) {
        c += texture(u_tex, v_uv + u_dir * float(i)).rgb * w[i];
        c += texture(u_tex, v_uv - u_dir * float(i)).rgb * w[i];
    }
    f_color = vec4(c, 1.0);
}
