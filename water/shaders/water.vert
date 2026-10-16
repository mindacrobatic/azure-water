#version 330

// Gerstner wave displacement on a radially-mapped grid, with analytic
// normals. Short waves fade out with distance to avoid geometric aliasing.

#define NUM_WAVES 8

in vec2 in_pos;              // grid position in world xz, relative to u_center

uniform mat4 u_view_proj;
uniform vec2 u_center;
uniform vec2 u_cam_xz;
uniform float u_time;
uniform vec2 u_wave_dir[NUM_WAVES];
uniform float u_wave_k[NUM_WAVES];
uniform float u_wave_amp[NUM_WAVES];
uniform float u_wave_q[NUM_WAVES];
uniform float u_wave_omega[NUM_WAVES];
uniform float u_amp_total;
uniform float u_near_fade;   // metres around the eye where waves flatten out

out vec3 v_world;
out vec3 v_normal;
out float v_height;
out float v_dist;

void main() {
    vec2 xz = in_pos + u_center;
    vec3 P = vec3(xz.x, 0.0, xz.y);
    float distCam = distance(xz, u_cam_xz);

    vec3 tanV = vec3(1.0, 0.0, 0.0);
    vec3 binV = vec3(0.0, 0.0, 1.0);
    float height = 0.0;

    for (int i = 0; i < NUM_WAVES; i++) {
        vec2 D = u_wave_dir[i];
        float k = u_wave_k[i];
        float A = u_wave_amp[i];
        float Q = u_wave_q[i];
        float w = u_wave_omega[i];
        float lam = 6.2831853 / k;

        float lod = 1.0 / (1.0 + pow(distCam / (lam * 6.0), 2.0));
        // Flatten the surface very close to the eye so the camera can skim
        // the water without clipping through wave geometry.
        float Aeff = A * lod * smoothstep(u_near_fade * 0.15, u_near_fade, distCam);

        float ph = k * dot(D, xz) + w * u_time;
        float s = sin(ph);
        float c = cos(ph);
        float QAk = Q * Aeff * k;

        P.x += Q * Aeff * D.x * c;
        P.z += Q * Aeff * D.y * c;
        P.y += Aeff * s;
        height += Aeff * s;

        tanV.x -= QAk * D.x * D.x * s;
        tanV.y += Aeff * k * D.x * c;
        tanV.z -= QAk * D.x * D.y * s;

        binV.x -= QAk * D.x * D.y * s;
        binV.y += Aeff * k * D.y * c;
        binV.z -= QAk * D.y * D.y * s;
    }

    vec3 N = normalize(cross(binV, tanV));
    if (N.y < 0.0) N = -N;

    v_world = P;
    v_normal = N;
    v_height = height / max(u_amp_total, 1e-3);
    v_dist = distCam;

    gl_Position = u_view_proj * vec4(P, 1.0);
}
