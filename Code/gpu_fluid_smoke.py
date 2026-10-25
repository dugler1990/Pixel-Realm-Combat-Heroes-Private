"""Camera-local GPU Stable Fluids smoke (Pavel / GPU-Gems lineage).

Owns its GL resources; uses the active GPUBackend GL context. CPU backends no-op.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_CLAMP_TO_EDGE,
    GL_COLOR_ATTACHMENT0,
    GL_COLOR_BUFFER_BIT,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_COMPLETE,
    GL_LINEAR,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_RGBA,
    GL_RGBA16F,
    GL_RGBA8,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLE_STRIP,
    GL_UNSIGNED_BYTE,
    GL_VERTEX_SHADER,
    glActiveTexture,
    glBindBuffer,
    glBindFramebuffer,
    glBindTexture,
    glBindVertexArray,
    glBlendFunc,
    glBufferData,
    glCheckFramebufferStatus,
    glClear,
    glDeleteBuffers,
    glDeleteFramebuffers,
    glDeleteProgram,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDrawArrays,
    glEnableVertexAttribArray,
    glFramebufferTexture2D,
    glGenBuffers,
    glGenFramebuffers,
    glGenTextures,
    glGenVertexArrays,
    glGetUniformLocation,
    glTexImage2D,
    glTexParameteri,
    glUniform1f,
    glUniform1i,
    glUniform2f,
    glUniform3f,
    glUniform4f,
    glUseProgram,
    glVertexAttribPointer,
    glViewport,
)
from OpenGL.GL.shaders import compileProgram, compileShader


def _compile(fs_src: str):
    return compileProgram(
        compileShader(_VERT, GL_VERTEX_SHADER),
        compileShader(fs_src, GL_FRAGMENT_SHADER),
    )


_VERT = """
#version 330 core
layout(location = 0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

_SPLAT = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_target;
uniform vec2 u_point;
uniform float u_radius;
uniform vec3 u_color;
uniform float u_aspect;
void main() {
    vec2 p = v_uv - u_point;
    p.x *= u_aspect;
    float d = exp(-dot(p, p) / max(u_radius, 1e-6));
    vec3 base = texture(u_target, v_uv).rgb;
    fragColor = vec4(base + u_color * d, 1.0);
}
"""

_ADVECT = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform sampler2D u_source;
uniform vec2 u_texel;
uniform float u_dt;
uniform float u_dissipation;
void main() {
    vec2 vel = texture(u_velocity, v_uv).xy;
    vec2 coord = v_uv - u_dt * vel * u_texel * vec2(1.0, 1.0) * 256.0;
    // scale: vel stored in UV-space units roughly; texel compensates
    coord = clamp(coord, u_texel, 1.0 - u_texel);
    fragColor = u_dissipation * texture(u_source, coord);
}
"""

# Simpler advect: velocity is in UV/sec, so coord = uv - dt * vel
_ADVECT2 = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform sampler2D u_source;
uniform float u_dt;
uniform float u_dissipation;
uniform vec2 u_texel;
void main() {
    vec2 vel = texture(u_velocity, v_uv).rg;
    vec2 coord = v_uv - vel * u_dt;
    coord = clamp(coord, u_texel, vec2(1.0) - u_texel);
    fragColor = texture(u_source, coord) * u_dissipation;
}
"""

_CURL = """
#version 330 core
precision highp float;
in vec2 v_uv;
out float fragColor;
uniform sampler2D u_velocity;
uniform vec2 u_texel;
void main() {
    float L = texture(u_velocity, v_uv - vec2(u_texel.x, 0.0)).y;
    float R = texture(u_velocity, v_uv + vec2(u_texel.x, 0.0)).y;
    float B = texture(u_velocity, v_uv - vec2(0.0, u_texel.y)).x;
    float T = texture(u_velocity, v_uv + vec2(0.0, u_texel.y)).x;
    fragColor = 0.5 * (R - L - (T - B));
}
"""

# curl outputs to R channel of RGBA
_CURL_RGBA = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform vec2 u_texel;
void main() {
    float L = texture(u_velocity, v_uv - vec2(u_texel.x, 0.0)).g;
    float R = texture(u_velocity, v_uv + vec2(u_texel.x, 0.0)).g;
    float B = texture(u_velocity, v_uv - vec2(0.0, u_texel.y)).r;
    float T = texture(u_velocity, v_uv + vec2(0.0, u_texel.y)).r;
    float curl = 0.5 * ((R - L) - (T - B));
    fragColor = vec4(curl, 0.0, 0.0, 1.0);
}
"""

_VORTICITY = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform sampler2D u_curl;
uniform vec2 u_texel;
uniform float u_curl_strength;
uniform float u_dt;
void main() {
    float L = texture(u_curl, v_uv - vec2(u_texel.x, 0.0)).r;
    float R = texture(u_curl, v_uv + vec2(u_texel.x, 0.0)).r;
    float B = texture(u_curl, v_uv - vec2(0.0, u_texel.y)).r;
    float T = texture(u_curl, v_uv + vec2(0.0, u_texel.y)).r;
    float C = texture(u_curl, v_uv).r;
    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    float len = length(force) + 1e-5;
    force = (force / len) * u_curl_strength * C;
    // Correct orientation: force = (d|curl|/dy, -d|curl|/dx) style
    force = vec2(force.y, -force.x);
    vec2 vel = texture(u_velocity, v_uv).rg;
    fragColor = vec4(vel + force * u_dt, 0.0, 1.0);
}
"""

_DIVERGENCE = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform vec2 u_texel;
void main() {
    float L = texture(u_velocity, v_uv - vec2(u_texel.x, 0.0)).r;
    float R = texture(u_velocity, v_uv + vec2(u_texel.x, 0.0)).r;
    float B = texture(u_velocity, v_uv - vec2(0.0, u_texel.y)).g;
    float T = texture(u_velocity, v_uv + vec2(0.0, u_texel.y)).g;
    float div = 0.5 * (R - L + T - B);
    fragColor = vec4(div, 0.0, 0.0, 1.0);
}
"""

_PRESSURE = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_pressure;
uniform sampler2D u_divergence;
uniform vec2 u_texel;
void main() {
    float L = texture(u_pressure, v_uv - vec2(u_texel.x, 0.0)).r;
    float R = texture(u_pressure, v_uv + vec2(u_texel.x, 0.0)).r;
    float B = texture(u_pressure, v_uv - vec2(0.0, u_texel.y)).r;
    float T = texture(u_pressure, v_uv + vec2(0.0, u_texel.y)).r;
    float C = texture(u_divergence, v_uv).r;
    float p = (L + R + B + T - C) * 0.25;
    fragColor = vec4(p, 0.0, 0.0, 1.0);
}
"""

_GRADIENT = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_pressure;
uniform sampler2D u_velocity;
uniform vec2 u_texel;
void main() {
    float L = texture(u_pressure, v_uv - vec2(u_texel.x, 0.0)).r;
    float R = texture(u_pressure, v_uv + vec2(u_texel.x, 0.0)).r;
    float B = texture(u_pressure, v_uv - vec2(0.0, u_texel.y)).r;
    float T = texture(u_pressure, v_uv + vec2(0.0, u_texel.y)).r;
    vec2 vel = texture(u_velocity, v_uv).rg;
    vel -= 0.5 * vec2(R - L, T - B);
    fragColor = vec4(vel, 0.0, 1.0);
}
"""

_FORCE = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_velocity;
uniform sampler2D u_density;
uniform vec2 u_wind;
uniform float u_buoyancy;
uniform float u_dt;
void main() {
    vec2 vel = texture(u_velocity, v_uv).rg;
    float d = texture(u_density, v_uv).r;
    // GL UV: +v is up the screen — buoyancy lifts dense smoke.
    vel += u_wind * u_dt;
    vel.y += u_buoyancy * d * u_dt;
    fragColor = vec4(vel, 0.0, 1.0);
}
"""

_CLEAR = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform vec4 u_value;
void main() { fragColor = u_value; }
"""

_DISPLAY_GROUND = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_density;
uniform float u_gain;
void main() {
    float d = texture(u_density, v_uv).r;
    float a = smoothstep(0.015, 0.28, d) * u_gain;
    a = clamp(a, 0.0, 0.5);
    // Warm near fire / denser cores, cooler blue-grey as it thins.
    vec3 cool = vec3(0.28, 0.34, 0.46);
    vec3 warm = vec3(0.78, 0.42, 0.18);
    vec3 col = mix(cool, warm, smoothstep(0.04, 0.40, d));
    fragColor = vec4(col, a);
}
"""

_DISPLAY_RISE = """
#version 330 core
precision highp float;
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_density;
uniform float u_gain;
uniform float u_rise;
void main() {
    // Sample density from below this pixel so the plume reads above the source.
    float a_acc = 0.0;
    vec3 col_acc = vec3(0.0);
    float wsum = 0.0;
    for (int i = 1; i <= 4; ++i) {
        float t = float(i) / 4.0;
        vec2 uv = v_uv - vec2(0.0, u_rise * t);
        if (uv.y < 0.0 || uv.y > 1.0) continue;
        float d = texture(u_density, uv).r;
        float w = (1.0 - 0.55 * t) * smoothstep(0.02, 0.35, d);
        vec3 cool = vec3(0.38, 0.40, 0.46);
        vec3 warm = vec3(0.72, 0.40, 0.20);
        // Higher samples cool off — height reads as warm→cool.
        col_acc += mix(cool, warm, smoothstep(0.04, 0.4, d) * (1.0 - t)) * w;
        a_acc += w;
        wsum += 1.0 - 0.55 * t;
    }
    float a = clamp(a_acc * u_gain * 0.48, 0.0, 0.38);
    vec3 col = (a_acc > 1e-4) ? (col_acc / max(a_acc, 1e-4)) : vec3(0.5);
    fragColor = vec4(col, a);
}
"""


@dataclass
class _Splat:
    u: float
    v: float
    density: float
    radius: float
    vel_u: float = 0.0
    vel_v: float = 0.0


class _FBO:
    __slots__ = ("tex", "fbo", "w", "h")

    def __init__(self, tex, fbo, w, h):
        self.tex = tex
        self.fbo = fbo
        self.w = w
        self.h = h


class _Pair:
    __slots__ = ("read", "write")

    def __init__(self, a: _FBO, b: _FBO):
        self.read = a
        self.write = b

    def swap(self):
        self.read, self.write = self.write, self.read


class GpuFluidSmoke:
    """Camera-local fluid smoke. Safe no-op if GL init fails or backend is CPU."""

    SIM = 128
    DYE = 256
    PRESSURE_ITERS = 18
    MAX_SPLATS = 24

    def __init__(self, backend=None):
        self.backend = backend
        self.enabled = False
        self._ready = False
        self._failed = False
        self._queue: list[_Splat] = []
        self._programs = {}
        self._vao = None
        self._vbo = None
        self._velocity = None
        self._density = None
        self._pressure = None
        self._divergence = None
        self._curl = None
        self._use_float = True
        # Tunables — keep curl modest; high vorticity confinement blows the dye into noise.
        self.vel_dissipation = 0.985
        self.den_dissipation = 0.968  # between soft fade and old chimney linger
        self.curl_strength = 24.0
        self.buoyancy = 1.22
        self.wind_scale = 0.10
        self.ground_gain = 0.75
        self.rise_gain = 0.88
        self.rise_uv = 0.14
        # Wind boosts swirl/lift gently; hard-capped so pin/storms can't destabilize.
        self.wind_curl_gain = 0.04
        self.wind_buoyancy_gain = 0.03
        self.max_curl_strength = 36.0
        self.max_buoyancy = 1.8

    # --- public API ---------------------------------------------------------
    def queue_splat(self, world_pos, *, amount=1.0, radius_px=48.0, rise=0.35):
        """Queue a density+velocity splat; UV resolved at step time."""
        if len(self._queue) >= self.MAX_SPLATS:
            self._queue.pop(0)
        self._queue.append(
            _Splat(
                u=float(world_pos[0]),  # temporarily store world; converted in step
                v=float(world_pos[1]),
                density=float(amount),
                radius=float(radius_px),
                vel_u=0.0,
                vel_v=-float(rise),  # up-screen after UV convert
            )
        )

    def step(self, dt, weather, camera_offset, view_size):
        if self._failed:
            return
        if not self._ready:
            if not self._try_init():
                return
        if dt is None or dt <= 0:
            dt = 1.0 / 30.0
        dt = min(float(dt), 0.05)

        ox, oy = float(camera_offset[0]), float(camera_offset[1])
        vw, vh = float(view_size[0]), float(view_size[1])
        if vw < 1 or vh < 1:
            return

        # Convert queued world splats → UV (top-left origin like pygame screen).
        # GL display UV: v=0 bottom. We store density in pygame-like UV (v=0 top)
        # by flipping V when sampling display... easier: store with v_gl = 1 - v_py.
        aspect = vw / vh
        splats_uv = []
        for s in self._queue:
            u = (s.u - ox) / vw
            v_py = (s.v - oy) / vh
            if u < -0.05 or u > 1.05 or v_py < -0.05 or v_py > 1.05:
                continue
            v = 1.0 - v_py  # to GL
            # radius in UV
            r = (s.radius / vh) ** 2
            vv = (-s.vel_v) * 0.85  # rise → +GL v
            vu = s.vel_u * 0.85
            splats_uv.append((u, v, s.density, r, vu, vv))
        self._queue.clear()

        wx = wy = 0.0
        wind_mag = 0.0
        if weather is not None:
            try:
                fx, fy = weather.calculate_wind_force()
                # Wind as UV force; magnitude also boosts curl/buoyancy below.
                wx = float(fx) * self.wind_scale * 0.15
                wy = -float(fy) * self.wind_scale * 0.15
                wind_mag = (float(fx) * float(fx) + float(fy) * float(fy)) ** 0.5
            except Exception:
                pass

        curl = min(
            self.max_curl_strength,
            self.curl_strength * (1.0 + self.wind_curl_gain * wind_mag),
        )
        buoy = min(
            self.max_buoyancy,
            self.buoyancy * (1.0 + self.wind_buoyancy_gain * wind_mag),
        )
        self._gl_step(dt, aspect, splats_uv, wx, wy, curl_strength=curl, buoyancy=buoy)

    def draw_ground(self):
        if not self._ready:
            return
        self._draw_display(self._programs["display_ground"], self.ground_gain, rise=False)

    def draw_rise(self):
        if not self._ready:
            return
        self._draw_display(self._programs["display_rise"], self.rise_gain, rise=True)

    def shutdown(self):
        if not self._ready:
            return
        try:
            for p in self._programs.values():
                glDeleteProgram(p)
            for pair in (self._velocity, self._density, self._pressure):
                if pair:
                    glDeleteTextures([pair.read.tex, pair.write.tex])
                    glDeleteFramebuffers(2, [pair.read.fbo, pair.write.fbo])
            for single in (self._divergence, self._curl):
                if single:
                    glDeleteTextures([single.tex])
                    glDeleteFramebuffers(1, [single.fbo])
            if self._vao:
                glDeleteVertexArrays(1, [self._vao])
            if self._vbo:
                glDeleteBuffers(1, [self._vbo])
        except Exception:
            pass
        self._ready = False

    # --- GL -----------------------------------------------------------------
    def _try_init(self) -> bool:
        backend = self.backend
        if backend is None or getattr(backend, "raw_surface", None) is not None:
            # CPU backend exposes raw_surface; GPU has None
            if backend is not None and type(backend).__name__ != "GPUBackend":
                self._failed = True
                return False
        try:
            self._init_gl()
            self._ready = True
            self.enabled = True
            return True
        except Exception as exc:
            print(f"[fluid_smoke] init failed: {exc}")
            self._failed = True
            return False

    def _create_fbo(self, w, h, internal, fmt, typ) -> _FBO:
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, internal, w, h, 0, fmt, typ, None)
        fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glBindTexture(GL_TEXTURE_2D, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"fluid FBO incomplete: {status}")
        return _FBO(tex, fbo, w, h)

    def _make_pair(self, w, h, internal, fmt, typ) -> _Pair:
        return _Pair(
            self._create_fbo(w, h, internal, fmt, typ),
            self._create_fbo(w, h, internal, fmt, typ),
        )

    def _init_gl(self):
        # Prefer float16 RGBA for all fields (widely supported).
        typ = GL_FLOAT
        try:
            t = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, t)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 4, 4, 0, GL_RGBA, typ, None)
            glBindTexture(GL_TEXTURE_2D, 0)
            glDeleteTextures([t])
            internal = GL_RGBA16F
            self._use_float = True
        except Exception:
            internal = GL_RGBA8
            typ = GL_UNSIGNED_BYTE
            self._use_float = False
        fmt = GL_RGBA

        s = self.SIM
        d = self.DYE
        self._velocity = self._make_pair(s, s, internal, fmt, typ)
        self._density = self._make_pair(d, d, internal, fmt, typ)
        self._pressure = self._make_pair(s, s, internal, fmt, typ)
        self._divergence = self._create_fbo(s, s, internal, fmt, typ)
        self._curl = self._create_fbo(s, s, internal, fmt, typ)

        self._programs = {
            "splat": _compile(_SPLAT),
            "advect": _compile(_ADVECT2),
            "curl": _compile(_CURL_RGBA),
            "vorticity": _compile(_VORTICITY),
            "divergence": _compile(_DIVERGENCE),
            "pressure": _compile(_PRESSURE),
            "gradient": _compile(_GRADIENT),
            "force": _compile(_FORCE),
            "clear": _compile(_CLEAR),
            "display_ground": _compile(_DISPLAY_GROUND),
            "display_rise": _compile(_DISPLAY_RISE),
        }

        # Fullscreen quad
        self._vao = glGenVertexArrays(1)
        self._vbo = glGenBuffers(1)
        verts = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        # Clear fields
        self._blit(self._programs["clear"], self._velocity.write, {"u_value": (0, 0, 0, 1)})
        self._velocity.swap()
        self._blit(self._programs["clear"], self._velocity.write, {"u_value": (0, 0, 0, 1)})
        self._velocity.swap()
        self._blit(self._programs["clear"], self._density.write, {"u_value": (0, 0, 0, 1)})
        self._density.swap()
        self._blit(self._programs["clear"], self._pressure.write, {"u_value": (0, 0, 0, 1)})
        self._pressure.swap()

    def _bind_draw(self, fbo: _FBO):
        glBindFramebuffer(GL_FRAMEBUFFER, fbo.fbo)
        glViewport(0, 0, fbo.w, fbo.h)

    def _blit(self, program, dest: _FBO, uniforms: dict, textures: dict | None = None):
        self._bind_draw(dest)
        glUseProgram(program)
        textures = textures or {}
        unit = 0
        for name, tex in textures.items():
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(GL_TEXTURE_2D, tex)
            loc = glGetUniformLocation(program, name)
            if loc >= 0:
                glUniform1i(loc, unit)
            unit += 1
        for name, val in uniforms.items():
            loc = glGetUniformLocation(program, name)
            if loc < 0:
                continue
            if isinstance(val, tuple) and len(val) == 4:
                glUniform4f(loc, *val)
            elif isinstance(val, tuple) and len(val) == 3:
                glUniform3f(loc, *val)
            elif isinstance(val, tuple) and len(val) == 2:
                glUniform2f(loc, *val)
            elif isinstance(val, float):
                glUniform1f(loc, val)
            elif isinstance(val, int):
                glUniform1i(loc, val)
        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glUseProgram(0)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def _gl_step(self, dt, aspect, splats_uv, wind_x, wind_y, *, curl_strength=None, buoyancy=None):
        if self.backend is not None:
            flush = getattr(self.backend, "_flush_batch", None)
            if callable(flush):
                flush()

        if curl_strength is None:
            curl_strength = self.curl_strength
        if buoyancy is None:
            buoyancy = self.buoyancy

        sim = self.SIM
        dye = self.DYE
        sim_texel = (1.0 / sim, 1.0 / sim)
        dye_texel = (1.0 / dye, 1.0 / dye)

        # Splats into density + velocity
        for u, v, dens, r, vu, vv in splats_uv:
            self._blit(
                self._programs["splat"],
                self._density.write,
                {
                    "u_point": (u, v),
                    "u_radius": max(r, 1e-5),
                    "u_color": (dens, dens * 0.95, dens * 0.9),
                    "u_aspect": aspect,
                },
                {"u_target": self._density.read.tex},
            )
            self._density.swap()
            self._blit(
                self._programs["splat"],
                self._velocity.write,
                {
                    "u_point": (u, v),
                    "u_radius": max(r * 1.2, 1e-5),
                    "u_color": (vu, vv, 0.0),
                    "u_aspect": aspect,
                },
                {"u_target": self._velocity.read.tex},
            )
            self._velocity.swap()

        # Forces
        self._blit(
            self._programs["force"],
            self._velocity.write,
            {
                "u_wind": (wind_x, wind_y),
                "u_buoyancy": float(buoyancy),
                "u_dt": dt,
            },
            {
                "u_velocity": self._velocity.read.tex,
                "u_density": self._density.read.tex,
            },
        )
        self._velocity.swap()

        # Curl + vorticity
        self._blit(
            self._programs["curl"],
            self._curl,
            {"u_texel": sim_texel},
            {"u_velocity": self._velocity.read.tex},
        )
        self._blit(
            self._programs["vorticity"],
            self._velocity.write,
            {
                "u_texel": sim_texel,
                "u_curl_strength": float(curl_strength),
                "u_dt": dt,
            },
            {
                "u_velocity": self._velocity.read.tex,
                "u_curl": self._curl.tex,
            },
        )
        self._velocity.swap()

        # Divergence
        self._blit(
            self._programs["divergence"],
            self._divergence,
            {"u_texel": sim_texel},
            {"u_velocity": self._velocity.read.tex},
        )

        # Clear pressure then Jacobi
        self._blit(self._programs["clear"], self._pressure.write, {"u_value": (0, 0, 0, 1)})
        self._pressure.swap()
        for _ in range(self.PRESSURE_ITERS):
            self._blit(
                self._programs["pressure"],
                self._pressure.write,
                {"u_texel": sim_texel},
                {
                    "u_pressure": self._pressure.read.tex,
                    "u_divergence": self._divergence.tex,
                },
            )
            self._pressure.swap()

        # Gradient subtract
        self._blit(
            self._programs["gradient"],
            self._velocity.write,
            {"u_texel": sim_texel},
            {
                "u_pressure": self._pressure.read.tex,
                "u_velocity": self._velocity.read.tex,
            },
        )
        self._velocity.swap()

        # Advect velocity
        self._blit(
            self._programs["advect"],
            self._velocity.write,
            {
                "u_dt": dt,
                "u_dissipation": self.vel_dissipation,
                "u_texel": sim_texel,
            },
            {
                "u_velocity": self._velocity.read.tex,
                "u_source": self._velocity.read.tex,
            },
        )
        self._velocity.swap()

        # Advect density (use velocity field)
        self._blit(
            self._programs["advect"],
            self._density.write,
            {
                "u_dt": dt,
                "u_dissipation": self.den_dissipation,
                "u_texel": dye_texel,
            },
            {
                "u_velocity": self._velocity.read.tex,
                "u_source": self._density.read.tex,
            },
        )
        self._density.swap()

        # Restore viewport to screen
        if self.backend is not None:
            w, h = self.backend.get_size()
            glViewport(0, 0, int(w), int(h))
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def _draw_display(self, program, gain, rise: bool):
        if self.backend is not None:
            flush = getattr(self.backend, "_flush_batch", None)
            if callable(flush):
                flush()
            w, h = self.backend.get_size()
            glViewport(0, 0, int(w), int(h))

        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glUseProgram(program)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._density.read.tex)
        glUniform1i(glGetUniformLocation(program, "u_density"), 0)
        glUniform1f(glGetUniformLocation(program, "u_gain"), float(gain))
        if rise:
            loc = glGetUniformLocation(program, "u_rise")
            if loc >= 0:
                glUniform1f(loc, float(self.rise_uv))
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glUseProgram(0)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
