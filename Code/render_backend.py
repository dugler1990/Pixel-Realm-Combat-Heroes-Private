import ctypes

import numpy as np
import pygame
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from Settings import DISPLAY_FLAGS, RENDER_BACKEND
from benchmark_runtime import BENCHMARK_RUNTIME


class RenderBackend:
    def get_size(self) -> tuple[int, int]:
        raise NotImplementedError

    def begin_frame(self, clear_color=(0, 0, 0)):
        raise NotImplementedError

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        raise NotImplementedError

    def fill(self, color, rect=None, flags=0):
        raise NotImplementedError

    def present(self):
        raise NotImplementedError

    @property
    def raw_surface(self) -> pygame.Surface | None:
        raise NotImplementedError

    def invalidate_texture(self, surface):
        """Drop any cached GPU texture for `surface`. No-op on backends without a cache."""
        pass

    def shutdown(self):
        """Release backend GPU resources. No-op on backends without any."""
        pass

    def draw_rect(self, color, rect, width=0):
        rect = pygame.Rect(rect)
        tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(tmp, color, tmp.get_rect(), width)
        self.blit(tmp, rect.topleft)

    def draw_circle(self, color, center, radius, width=0):
        size = (radius * 2, radius * 2)
        tmp = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.circle(tmp, color, (radius, radius), radius, width)
        self.blit(tmp, (center[0] - radius, center[1] - radius))

    def compose(self, size=None):
        """Offscreen SRCALPHA surface sized to `size` (default: full backend size).

        Caller draws onto it, then `backend.blit(surface, dest)` to composite.
        """
        return pygame.Surface(size or self.get_size(), pygame.SRCALPHA)


class CPUBackend(RenderBackend):
    def __init__(self, surface: pygame.Surface):
        self._surface = surface

    def get_size(self) -> tuple[int, int]:
        return self._surface.get_size()

    def begin_frame(self, clear_color=(0, 0, 0)):
        self._surface.fill(clear_color)

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        if area is not None:
            self._surface.blit(surface, dest, area=area, special_flags=flags)
        else:
            self._surface.blit(surface, dest, special_flags=flags)

    def fill(self, color, rect=None, flags=0):
        if rect is not None:
            self._surface.fill(color, rect, special_flags=flags)
        else:
            self._surface.fill(color, special_flags=flags)

    def present(self):
        pygame.display.update()

    @property
    def raw_surface(self) -> pygame.Surface:
        return self._surface

    def draw_shadow(self, *args, **kwargs):
        pass

    def draw_light(self, *args, **kwargs):
        pass

    def begin_light_pass(self, *args, **kwargs):
        pass

    def end_light_pass(self, *args, **kwargs):
        pass

    def composite_lights(self, *args, **kwargs):
        pass

    def draw_grass_instances(self, *args, **kwargs):
        pass

    def build_grass_atlas(self, *args, **kwargs):
        pass

    @property
    def grass_atlas_ready(self) -> bool:
        return False


# Batch vertex shader — per-vertex position (pixel coords), texcoord (atlas UV), tint.
# Only u_screen_size is a per-frame uniform; no per-sprite uniforms needed.
_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 a_position;
layout(location = 1) in vec2 a_texcoord;
layout(location = 2) in vec4 a_tint;

uniform vec2 u_screen_size;

out vec2 v_texcoord;
out vec4 v_tint;

void main()
{
    vec2 ndc = vec2(
        a_position.x / u_screen_size.x * 2.0 - 1.0,
        1.0 - a_position.y / u_screen_size.y * 2.0
    );
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_texcoord = a_texcoord;
    v_tint = a_tint;
}
"""

_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_texcoord;
in vec4 v_tint;

uniform sampler2D u_tex;

out vec4 frag_color;

void main()
{
    frag_color = texture(u_tex, v_texcoord) * v_tint;
}
"""

# --- Instanced grass blade pipeline (Phase A proof) -------------------------
# Each blade is one instanced quad. The vertex shader rotates the quad around
# its center by a per-instance angle — this is the whole point: per-blade
# rotation happens on the GPU instead of CPU pygame.transform.rotate.
# Per-vertex: a_corner (unit quad in [-0.5, +0.5], divisor 0).
# Per-instance (divisor 1): center px, halfsize px, angle rad, uv rect, tint.
_GRASS_VERTEX_SHADER = """
#version 330 core
layout(location = 3) in vec2  a_corner;    // unit quad [-0.5, +0.5]
layout(location = 4) in vec2  a_center;    // blade center, screen px
layout(location = 5) in vec2  a_halfsize;  // half blade size, px
layout(location = 6) in float a_angle;     // radians
layout(location = 7) in vec4  a_uvrect;    // (u0, v0, u1, v1)
layout(location = 8) in vec4  a_tint;

uniform vec2 u_screen_size;

out vec2 v_texcoord;
out vec4 v_tint;

void main()
{
    vec2 local = a_corner * (a_halfsize * 2.0);
    float c = cos(a_angle);
    float s = sin(a_angle);
    // CCW in screen space (y-down) to match pygame.transform.rotate sign.
    vec2 rot = vec2(c * local.x + s * local.y, -s * local.x + c * local.y);
    vec2 px = a_center + rot;
    vec2 ndc = vec2(
        px.x / u_screen_size.x * 2.0 - 1.0,
        1.0 - px.y / u_screen_size.y * 2.0
    );
    gl_Position = vec4(ndc, 0.0, 1.0);
    vec2 t = a_corner + 0.5;                       // [-0.5,0.5] -> [0,1]
    v_texcoord = mix(a_uvrect.xy, a_uvrect.zw, t); // top corner -> v0
    v_tint = a_tint;
}
"""

_GRASS_FRAGMENT_SHADER = _FRAGMENT_SHADER  # identical: texture(u_tex, uv) * tint

_GRASS_INST_FLOATS = 13  # center(2) + halfsize(2) + angle(1) + uvrect(4) + tint(4)

_DEFAULT_BLEND_FUNC = (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
_BLEND_FUNC_OVERRIDES = {
    pygame.BLEND_RGBA_ADD: (GL_ONE, GL_ONE),
    pygame.BLEND_RGB_MULT: (GL_DST_COLOR, GL_ZERO),
}

# Vertex layout: (x, y, u, v, r, g, b, a) — 8 floats × 4 bytes = 32 bytes stride.
# Two triangles per quad = 6 vertices × 8 floats = 48 floats per sprite.
_FLOATS_PER_VERT = 8
_VERTS_PER_QUAD = 6
_FLOATS_PER_QUAD = _FLOATS_PER_VERT * _VERTS_PER_QUAD  # 48
_MAX_BATCH_SIZE = 2048
_BATCH_BUF_FLOATS = _MAX_BATCH_SIZE * _FLOATS_PER_QUAD
_BATCH_BUF_BYTES = _BATCH_BUF_FLOATS * ctypes.sizeof(GLfloat)


class GPUBackend(RenderBackend):
    """PyOpenGL batched sprite renderer. raw_surface is None by design."""

    def __init__(self, width, height):
        self._width = width
        self._height = height

        self._shader = compileProgram(
            compileShader(_VERTEX_SHADER, GL_VERTEX_SHADER),
            compileShader(_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
        )
        self._u_screen_size = glGetUniformLocation(self._shader, "u_screen_size")
        self._u_tex = glGetUniformLocation(self._shader, "u_tex")

        # VAO/VBO — dynamic batch buffer, pre-allocated for _MAX_BATCH_SIZE quads.
        # Stride: 8 floats (pos×2, uv×2, tint×4).
        self._vao = glGenVertexArrays(1)
        self._vbo = glGenBuffers(1)
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, _BATCH_BUF_BYTES, None, GL_DYNAMIC_DRAW)
        stride = _FLOATS_PER_VERT * ctypes.sizeof(GLfloat)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(2 * ctypes.sizeof(GLfloat)))
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(4 * ctypes.sizeof(GLfloat)))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        self._texture = self._make_texture()
        self._white_texture = self._make_texture(np.array([255, 255, 255, 255], dtype=np.uint8), 1, 1)
        self._atlas_texture = None
        self._atlas_uv = {}
        self._large_cache: dict[int, int] = {}  # id(surface) → GL texture handle

        # Batch state
        self._batch_verts = np.zeros(_BATCH_BUF_FLOATS, dtype=np.float32)
        self._batch_count = 0
        self._batch_texture = None

        # Per-frame blit batching diagnostics. A blit only batches (no draw call of its own)
        # when it hits the atlas; the other two paths each force a flush. Split lets us tell a
        # timing-miss (had a cache_key but loaded after build_atlas -> prewarm fixes it) from
        # expected scratch (no stable id: UI/debug/recolored frames). Reset each present().
        self._blit_atlas = 0          # atlas hit -> batched
        self._blit_flush_keyed = 0    # had cache_key but missed atlas (large-cache / atlas-miss)
        self._blit_flush_nokey = 0    # no usable cache_key -> re-uploaded scratch every frame
        self.last_blit_stats = (0, 0, 0)

        self._init_grass_pipeline()
        self._init_light_pipeline()

        glEnable(GL_BLEND)
        glBlendFunc(*_DEFAULT_BLEND_FUNC)
        glViewport(0, 0, width, height)

    @staticmethod
    def _make_texture(pixels=None, width=1, height=1):
        texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        if pixels is not None:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels)
        glBindTexture(GL_TEXTURE_2D, 0)
        return texture

    def get_size(self) -> tuple[int, int]:
        return (self._width, self._height)

    def _push_batch(self, texture, dest_rect, tex_rect, tint=(1.0, 1.0, 1.0, 1.0)):
        if texture != self._batch_texture or self._batch_count >= _MAX_BATCH_SIZE:
            self._flush_batch()
            self._batch_texture = texture
        x, y, w, h = dest_rect
        u0, v0, u1, v1 = tex_rect
        r, g, b, a = tint
        i = self._batch_count * _FLOATS_PER_QUAD
        self._batch_verts[i:i + _FLOATS_PER_QUAD] = [
            x,     y,     u0, v0, r, g, b, a,
            x + w, y,     u1, v0, r, g, b, a,
            x + w, y + h, u1, v1, r, g, b, a,
            x,     y,     u0, v0, r, g, b, a,
            x + w, y + h, u1, v1, r, g, b, a,
            x,     y + h, u0, v1, r, g, b, a,
        ]
        self._batch_count += 1

    def _push_quad(self, texture, corners, uv_rect, tint=(1.0, 1.0, 1.0, 1.0)):
        """Like _push_batch but with 4 explicit corner (x,y) points (TL, TR, BR, BL),
        so the quad can be a sheared parallelogram (used for directional shadows)."""
        if texture != self._batch_texture or self._batch_count >= _MAX_BATCH_SIZE:
            self._flush_batch()
            self._batch_texture = texture
        tl, tr, br, bl = corners
        u0, v0, u1, v1 = uv_rect
        r, g, b, a = tint
        i = self._batch_count * _FLOATS_PER_QUAD
        self._batch_verts[i:i + _FLOATS_PER_QUAD] = [
            tl[0], tl[1], u0, v0, r, g, b, a,
            tr[0], tr[1], u1, v0, r, g, b, a,
            br[0], br[1], u1, v1, r, g, b, a,
            tl[0], tl[1], u0, v0, r, g, b, a,
            br[0], br[1], u1, v1, r, g, b, a,
            bl[0], bl[1], u0, v1, r, g, b, a,
        ]
        self._batch_count += 1

    def _flush_batch(self):
        if self._batch_count == 0:
            return
        n = self._batch_count
        data = self._batch_verts[:n * _FLOATS_PER_QUAD]

        glUseProgram(self._shader)
        glUniform2f(self._u_screen_size, float(self._width), float(self._height))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._batch_texture)
        glUniform1i(self._u_tex, 0)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        # Orphan the buffer before writing — avoids stalling on driver waiting for
        # the previous draw to finish reading it when there are multiple flushes/frame.
        glBufferData(GL_ARRAY_BUFFER, _BATCH_BUF_BYTES, None, GL_DYNAMIC_DRAW)
        glBufferSubData(GL_ARRAY_BUFFER, 0, data.nbytes, data)
        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, n * _VERTS_PER_QUAD)
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)

        self._batch_count = 0
        self._batch_texture = None

    def begin_frame(self, clear_color=(0, 0, 0)):
        self._flush_batch()  # safety — should be 0 at frame start
        r, g, b = clear_color[:3]
        glClearColor(r / 255.0, g / 255.0, b / 255.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

    @staticmethod
    def _dest_topleft(dest):
        if hasattr(dest, "topleft"):
            return dest.topleft
        return (dest[0], dest[1])

    def build_atlas(self):
        from ImageCache import ImageCache

        # Collect all ImageCache surfaces, deduplicated by id().
        # These are class-level dicts held for program lifetime → ids permanently stable.
        seen, surfs = set(), []
        for s in list(ImageCache.cache.values()) + list(ImageCache._scaled_cache.values()):
            if id(s) not in seen:
                seen.add(id(s)); surfs.append(s)
        for frame_list in ImageCache._folder_cache.values():
            for s in frame_list:
                if id(s) not in seen:
                    seen.add(id(s)); surfs.append(s)

        max_gl = glGetIntegerv(GL_MAX_TEXTURE_SIZE)
        ATLAS = min(4096, int(max_gl))
        PAD = 1
        # Exclude large one-off surfaces (backgrounds, UI panels) that would fill the
        # atlas before animation frames get a chance. Sprites > 512px in either dimension
        # are almost never animation frames — they're map art, menu screens, etc.
        MAX_SPRITE_DIM = 512
        surfs.sort(key=lambda s: s.get_height(), reverse=True)

        canvas = pygame.Surface((ATLAS, ATLAS), pygame.SRCALPHA)
        canvas.fill((0, 0, 0, 0))
        uv = {}
        x, y, row_h = PAD, PAD, 0
        packed = skipped_too_large = skipped_atlas_full = skipped_oversized = 0

        for s in surfs:
            w, h = s.get_size()
            if w > MAX_SPRITE_DIM or h > MAX_SPRITE_DIM:
                skipped_oversized += 1; continue  # not an animation frame — scratch

            if w > ATLAS - PAD * 2 or h > ATLAS - PAD * 2:
                skipped_too_large += 1; continue  # sprite too large — scratch fallback, keep going

            if x + w + PAD > ATLAS:
                y += row_h + PAD; x = PAD; row_h = 0

            if y + h + PAD > ATLAS:
                skipped_atlas_full += 1; continue  # skip this sprite, smaller ones may still fit

            canvas.blit(s, (x, y))
            uv[id(s)] = (x / ATLAS, y / ATLAS, (x + w) / ATLAS, (y + h) / ATLAS)
            row_h = max(row_h, h); x += w + PAD
            packed += 1

        pixels = pygame.image.tostring(canvas.convert_alpha(), "RGBA", False)
        self._atlas_texture = self._make_texture()
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, ATLAS, ATLAS, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels)
        glBindTexture(GL_TEXTURE_2D, 0)
        self._atlas_uv = uv
        skipped = skipped_oversized + skipped_too_large + skipped_atlas_full
        total = packed + skipped
        print(f"[ATLAS] packed={packed} skipped_oversized={skipped_oversized} "
              f"skipped_too_large={skipped_too_large} skipped_atlas_full={skipped_atlas_full} "
              f"atlas_size={ATLAS} occupancy={packed}/{total} ({100 * packed // total if total else 0}%)",
              flush=True)

    # --- instanced grass blade pipeline (Phase A proof) ---------------------

    def _init_grass_pipeline(self):
        self._grass_shader = compileProgram(
            compileShader(_GRASS_VERTEX_SHADER, GL_VERTEX_SHADER),
            compileShader(_GRASS_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
        )
        self._u_grass_screen = glGetUniformLocation(self._grass_shader, "u_screen_size")
        self._u_grass_tex = glGetUniformLocation(self._grass_shader, "u_tex")
        self._grass_atlas_texture = None
        self._grass_blade_uv_arr = None     # (n_blades, 4) float32
        self._grass_blade_half_arr = None   # (n_blades, 2) float32
        self._grass_inst_capacity = 0       # bytes currently allocated in instance VBO

        f = ctypes.sizeof(GLfloat)
        self._grass_vao = glGenVertexArrays(1)
        glBindVertexArray(self._grass_vao)

        # Static unit-corner quad (two triangles), centered pivot. Divisor 0.
        corners = np.array([
            -0.5, -0.5,  0.5, -0.5,  0.5, 0.5,
            -0.5, -0.5,  0.5,  0.5, -0.5, 0.5,
        ], dtype=np.float32)
        self._grass_corner_vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._grass_corner_vbo)
        glBufferData(GL_ARRAY_BUFFER, corners.nbytes, corners, GL_STATIC_DRAW)
        glEnableVertexAttribArray(3)
        glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, 2 * f, ctypes.c_void_p(0))
        glVertexAttribDivisor(3, 0)

        # Per-instance VBO (divisor 1). Layout matches _GRASS_INST_FLOATS.
        self._grass_inst_vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._grass_inst_vbo)
        istride = _GRASS_INST_FLOATS * f
        glEnableVertexAttribArray(4)  # a_center  @ 0
        glVertexAttribPointer(4, 2, GL_FLOAT, GL_FALSE, istride, ctypes.c_void_p(0))
        glVertexAttribDivisor(4, 1)
        glEnableVertexAttribArray(5)  # a_halfsize @ 2
        glVertexAttribPointer(5, 2, GL_FLOAT, GL_FALSE, istride, ctypes.c_void_p(2 * f))
        glVertexAttribDivisor(5, 1)
        glEnableVertexAttribArray(6)  # a_angle @ 4
        glVertexAttribPointer(6, 1, GL_FLOAT, GL_FALSE, istride, ctypes.c_void_p(4 * f))
        glVertexAttribDivisor(6, 1)
        glEnableVertexAttribArray(7)  # a_uvrect @ 5
        glVertexAttribPointer(7, 4, GL_FLOAT, GL_FALSE, istride, ctypes.c_void_p(5 * f))
        glVertexAttribDivisor(7, 1)
        glEnableVertexAttribArray(8)  # a_tint @ 9
        glVertexAttribPointer(8, 4, GL_FLOAT, GL_FALSE, istride, ctypes.c_void_p(9 * f))
        glVertexAttribDivisor(8, 1)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

    @property
    def grass_atlas_ready(self):
        return self._grass_atlas_texture is not None

    def build_grass_atlas(self, blade_surfaces):
        """Pack the (few, tiny) blade images into one dedicated GL texture once.
        Records per-blade UV rects and half-sizes for instance expansion."""
        if self._grass_atlas_texture is not None or not blade_surfaces:
            return
        PAD = 1
        sizes = [s.get_size() for s in blade_surfaces]
        atlas_w = sum(w + PAD for w, _ in sizes) + PAD
        atlas_h = max(h for _, h in sizes) + PAD * 2

        canvas = pygame.Surface((atlas_w, atlas_h), pygame.SRCALPHA)
        canvas.fill((0, 0, 0, 0))
        uvs, halves = [], []
        x = PAD
        for s, (w, h) in zip(blade_surfaces, sizes):
            canvas.blit(s, (x, PAD))  # colorkey'd black -> transparent on SRCALPHA
            uvs.append((x / atlas_w, PAD / atlas_h, (x + w) / atlas_w, (PAD + h) / atlas_h))
            halves.append((w / 2.0, h / 2.0))
            x += w + PAD

        pixels = pygame.image.tostring(canvas.convert_alpha(), "RGBA", False)
        self._grass_atlas_texture = self._make_texture()
        glBindTexture(GL_TEXTURE_2D, self._grass_atlas_texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, atlas_w, atlas_h, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, pixels)
        glBindTexture(GL_TEXTURE_2D, 0)
        self._grass_blade_uv_arr = np.asarray(uvs, dtype=np.float32)
        self._grass_blade_half_arr = np.asarray(halves, dtype=np.float32)

    def draw_grass_instances(self, raw, count, shade_amount):
        """raw: (count, 4) float array of [center_x, center_y, blade_id, angle_deg].
        Expands to the full instance layout (vectorized) and issues ONE
        glDrawArraysInstanced for the whole visible field."""
        if count == 0 or self._grass_atlas_texture is None:
            return
        raw = np.asarray(raw, dtype=np.float32)
        bid = raw[:, 2].astype(np.intp)
        deg = raw[:, 3]

        inst = np.empty((count, _GRASS_INST_FLOATS), dtype=np.float32)
        inst[:, 0:2] = raw[:, 0:2]                       # center
        inst[:, 2:4] = self._grass_blade_half_arr[bid]   # halfsize
        inst[:, 4] = np.deg2rad(deg)                     # angle
        inst[:, 5:9] = self._grass_blade_uv_arr[bid]     # uv rect
        c = np.clip(1.0 - (float(shade_amount) / 255.0) * (np.abs(deg) / 90.0), 0.0, 1.0)
        inst[:, 9] = c; inst[:, 10] = c; inst[:, 11] = c  # shade tint rgb
        inst[:, 12] = 1.0                                 # tint alpha
        data = inst.reshape(-1)

        self._flush_batch()  # keep grass behind sprites pushed later this frame
        glUseProgram(self._grass_shader)
        glUniform2f(self._u_grass_screen, float(self._width), float(self._height))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._grass_atlas_texture)
        glUniform1i(self._u_grass_tex, 0)
        glBindVertexArray(self._grass_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._grass_inst_vbo)
        nbytes = data.nbytes
        if nbytes > self._grass_inst_capacity:
            self._grass_inst_capacity = nbytes
        glBufferData(GL_ARRAY_BUFFER, self._grass_inst_capacity, None, GL_DYNAMIC_DRAW)
        glBufferSubData(GL_ARRAY_BUFFER, 0, nbytes, data)
        glDrawArraysInstanced(GL_TRIANGLES, 0, _VERTS_PER_QUAD, count)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)

        if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
            BENCHMARK_RUNTIME.metrics.record_gpu_draw_call()

    # --- day/night light-map (Phase L) -------------------------------------
    # An offscreen FBO is cleared to a time-of-day ambient, lights are drawn into
    # it additively (radial brush), then the whole scene is multiplied by it.

    def _init_light_pipeline(self):
        # Screen-sized color texture, linear-filtered for a smooth light-map.
        self._light_tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._light_tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self._width, self._height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, None)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._light_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self._light_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self._light_tex, 0)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"light FBO incomplete: {status}")

        self._light_brush_tex = self._make_radial_brush()

    @staticmethod
    def _make_radial_brush(size=128, falloff=2.2):
        """Soft radial gradient (white center -> black edge), linear-filtered. The
        reusable light 'shape'; per-light color/intensity come from the draw tint."""
        coords = np.linspace(-1.0, 1.0, size, dtype=np.float32)
        xx, yy = np.meshgrid(coords, coords)
        d = np.sqrt(xx * xx + yy * yy)
        b = (np.clip(1.0 - d, 0.0, 1.0) ** falloff * 255.0).astype(np.uint8)
        rgba = np.ascontiguousarray(np.dstack([b, b, b, b]))
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, size, size, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba)
        glBindTexture(GL_TEXTURE_2D, 0)
        return tex

    def begin_light_pass(self, ambient):
        """Bind the light FBO and clear it to the ambient darkness floor [0,1]."""
        self._flush_batch()  # commit any pending world draws to the default framebuffer
        glBindFramebuffer(GL_FRAMEBUFFER, self._light_fbo)
        glViewport(0, 0, self._width, self._height)
        a = max(0.0, min(1.0, float(ambient)))
        glClearColor(a, a, a, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        glBlendFunc(GL_ONE, GL_ONE)  # additive accumulation of lights

    def draw_light(self, center, radius, color):
        """Add one radial light into the light-map. color is (r,g,b) with intensity
        already folded in (values may exceed 1; the RGBA8 target clamps)."""
        if radius <= 0:
            return
        cx, cy = center
        r = float(radius)
        dest_rect = (cx - r, cy - r, 2.0 * r, 2.0 * r)
        tint = (color[0], color[1], color[2], 1.0)
        self._push_batch(self._light_brush_tex, dest_rect, (0.0, 0.0, 1.0, 1.0), tint)

    def end_light_pass(self):
        self._flush_batch()  # flush accumulated light quads into the FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, self._width, self._height)
        glBlendFunc(*_DEFAULT_BLEND_FUNC)

    def composite_lights(self):
        """Multiply the default framebuffer (the drawn world) by the light-map.
        tex_rect V is flipped because the FBO stores screen-top at v=1."""
        self._flush_batch()
        glBlendFunc(GL_DST_COLOR, GL_ZERO)
        self._push_batch(self._light_tex, (0, 0, self._width, self._height), (0.0, 1.0, 1.0, 0.0))
        self._flush_batch()
        glBlendFunc(*_DEFAULT_BLEND_FUNC)

    def draw_shadow(self, image, corners, cache_key, strength):
        """Draw a dark, sheared silhouette of `image` (a directional shadow) at the
        4 given screen corners (TL, TR, BR, BL). Reuses the sprite's already-resident
        atlas / large-cache texture (no re-upload); scratch-uploads only as a fallback.
        tint=(0,0,0,strength) under default alpha blend -> darkens the ground by the
        sprite's alpha silhouette."""
        if strength <= 0:
            return
        atlas_uv = self._atlas_uv.get(cache_key) if cache_key is not None else None
        if atlas_uv is not None:
            texture, uv = self._atlas_texture, atlas_uv
        elif cache_key is not None and cache_key in self._large_cache:
            texture, uv = self._large_cache[cache_key], (0.0, 0.0, 1.0, 1.0)
        else:
            w, h = image.get_size()
            if w == 0 or h == 0:
                return
            pixels = pygame.image.tostring(image.convert_alpha(), "RGBA", False)
            texture, uv = self._texture, (0.0, 0.0, 1.0, 1.0)
            glBindTexture(GL_TEXTURE_2D, texture)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels)
            glBindTexture(GL_TEXTURE_2D, 0)

        self._push_quad(texture, corners, uv, (0.0, 0.0, 0.0, float(strength)))
        if texture != self._atlas_texture:
            # non-atlas (large-cache / scratch) can't batch with atlas draws — flush now
            self._flush_batch()

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        src = surface.subsurface(area) if area is not None else surface
        width, height = src.get_size()
        if width == 0 or height == 0:
            return

        # area= calls cannot use atlas UV (which covers the full surface, not the sub-rect).
        # Guard kept even though no atlas-eligible sprite currently uses area=, because the
        # assumption is non-obvious and someone adding area= to a sprite blit later shouldn't
        # have to know about this constraint.
        atlas_uv = (self._atlas_uv.get(cache_key)
                    if (cache_key is not None and area is None) else None)

        if atlas_uv is not None:
            self._blit_atlas += 1
            texture = self._atlas_texture
            tex_rect = atlas_uv
        elif cache_key is not None and area is None:
            self._blit_flush_keyed += 1
            # Persistent cache for large surfaces (ground, weather frames, etc.) that
            # have stable ids but exceed the atlas size cap. Upload once, reuse every frame.
            gl_tex = self._large_cache.get(cache_key)
            if gl_tex is None:
                pixels = pygame.image.tostring(src.convert_alpha(), "RGBA", False)
                gl_tex = self._make_texture()
                glBindTexture(GL_TEXTURE_2D, gl_tex)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0,
                             GL_RGBA, GL_UNSIGNED_BYTE, pixels)
                glBindTexture(GL_TEXTURE_2D, 0)
                self._large_cache[cache_key] = gl_tex
                if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
                    BENCHMARK_RUNTIME.metrics.record_gpu_texture_upload(0.0)
            texture = gl_tex
            tex_rect = (0.0, 0.0, 1.0, 1.0)
        else:
            # True scratch — no cache_key or area= (health bars, debug rects, etc.)
            # convert_alpha() normalizes both opaque and SRCALPHA surfaces to RGBA layout.
            self._blit_flush_nokey += 1
            texture = self._texture
            tex_rect = (0.0, 0.0, 1.0, 1.0)
            pixels = pygame.image.tostring(src.convert_alpha(), "RGBA", False)
            glBindTexture(GL_TEXTURE_2D, texture)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels)
            glBindTexture(GL_TEXTURE_2D, 0)
            if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
                BENCHMARK_RUNTIME.metrics.record_gpu_texture_upload(0.0)

        dest_x, dest_y = self._dest_topleft(dest)
        dest_rect = (dest_x, dest_y, width, height)
        blend_func = _BLEND_FUNC_OVERRIDES.get(flags)

        if blend_func is not None:
            # Fullscreen overlay — flush sprite batch first to preserve Z-order,
            # draw as singleton with override blend, restore default.
            self._flush_batch()
            glBlendFunc(*blend_func)
            self._push_batch(texture, dest_rect, tex_rect)
            self._flush_batch()
            glBlendFunc(*_DEFAULT_BLEND_FUNC)
        elif texture != self._atlas_texture:
            # Scratch draw — flush atlas batch first to preserve Z-order, draw immediately.
            self._push_batch(texture, dest_rect, tex_rect)
            self._flush_batch()
        else:
            self._push_batch(texture, dest_rect, tex_rect)

        if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
            BENCHMARK_RUNTIME.metrics.record_gpu_draw_call()

    def fill(self, color, rect=None, flags=0):
        if rect is None:
            dest_rect = (0, 0, self._width, self._height)
        else:
            r = pygame.Rect(rect)
            dest_rect = (r.x, r.y, r.width, r.height)
        c = pygame.Color(color)
        tint = (c.r / 255.0, c.g / 255.0, c.b / 255.0, c.a / 255.0)
        blend_func = _BLEND_FUNC_OVERRIDES.get(flags)
        if blend_func is not None:
            self._flush_batch()
            glBlendFunc(*blend_func)
            self._push_batch(self._white_texture, dest_rect, (0.0, 0.0, 1.0, 1.0), tint)
            self._flush_batch()
            glBlendFunc(*_DEFAULT_BLEND_FUNC)
        else:
            self._push_batch(self._white_texture, dest_rect, (0.0, 0.0, 1.0, 1.0), tint)
            self._flush_batch()

    def draw_rect(self, color, rect, width=0):
        r = pygame.Rect(rect)
        if width == 0:
            self.fill(color, r)
        else:
            self.fill(color, pygame.Rect(r.x,             r.y,              r.width, width))
            self.fill(color, pygame.Rect(r.x,             r.bottom - width, r.width, width))
            self.fill(color, pygame.Rect(r.x,             r.y,              width,   r.height))
            self.fill(color, pygame.Rect(r.right - width, r.y,              width,   r.height))

    def present(self):
        self._flush_batch()
        pygame.display.flip()
        # snapshot per-frame batching stats for the debug overlay, then reset
        self.last_blit_stats = (self._blit_atlas, self._blit_flush_keyed, self._blit_flush_nokey)
        self._blit_atlas = self._blit_flush_keyed = self._blit_flush_nokey = 0

    @property
    def raw_surface(self):
        return None

    def invalidate_texture(self, surface):
        key = id(surface)
        gl_tex = self._large_cache.pop(key, None)
        if gl_tex is not None:
            glDeleteTextures([gl_tex])

    def shutdown(self):
        texture_ids = [self._texture, self._white_texture]
        if self._atlas_texture is not None:
            texture_ids.append(self._atlas_texture)
        if getattr(self, "_grass_atlas_texture", None) is not None:
            texture_ids.append(self._grass_atlas_texture)
        if getattr(self, "_light_tex", None) is not None:
            texture_ids.append(self._light_tex)
        if getattr(self, "_light_brush_tex", None) is not None:
            texture_ids.append(self._light_brush_tex)
        texture_ids.extend(self._large_cache.values())
        glDeleteTextures(texture_ids)
        self._large_cache.clear()
        glDeleteVertexArrays(1, [self._vao])
        glDeleteBuffers(1, [self._vbo])
        if getattr(self, "_grass_vao", None) is not None:
            glDeleteVertexArrays(1, [self._grass_vao])
            glDeleteBuffers(1, [self._grass_corner_vbo])
            glDeleteBuffers(1, [self._grass_inst_vbo])
        if getattr(self, "_light_fbo", None) is not None:
            glDeleteFramebuffers(1, [self._light_fbo])

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass


class StubBackend(RenderBackend):
    """A no-op render backend for the headless authoritative server.

    The server runs the REAL Level4 simulation but renders NOTHING, so every
    draw call here is a no-op and nothing ever opens a window or an OpenGL
    context (unlike CPUBackend/GPUBackend, which both call
    pygame.display.set_mode()). A small offscreen software surface backs
    raw_surface/compose so any code that reads a surface still gets a valid
    (never-presented) target instead of crashing.

    It implements the union of the RenderBackend + GPUBackend draw surface the
    game's draw half touches (lighting passes, grass instancing, shadows) so the
    full Level4.run() draw path can execute headless without a GPU. The server
    proper will call a sim-only path and never these, but keeping StubBackend
    fully draw-safe lets the characterization tests run real run() headless.
    """

    def __init__(self, width: int, height: int):
        self._size = (int(width), int(height))
        self._surface = pygame.Surface(self._size)

    def get_size(self) -> tuple[int, int]:
        return self._size

    def begin_frame(self, clear_color=(0, 0, 0)):
        pass

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        pass

    def fill(self, color, rect=None, flags=0):
        pass

    def present(self):
        pass

    @property
    def raw_surface(self) -> pygame.Surface:
        return self._surface

    # --- GPU-only draw helpers some draw paths call directly (all no-ops) ---
    def draw_shadow(self, *args, **kwargs):
        pass

    def draw_light(self, *args, **kwargs):
        pass

    def draw_grass_instances(self, *args, **kwargs):
        pass

    def build_grass_atlas(self, *args, **kwargs):
        pass

    @property
    def grass_atlas_ready(self) -> bool:
        # Report "ready" so the draw path skips build_grass_atlas entirely.
        return True

    def begin_light_pass(self, *args, **kwargs):
        pass

    def end_light_pass(self, *args, **kwargs):
        pass

    def composite_lights(self, *args, **kwargs):
        pass


def create_backend(width: int, height: int) -> RenderBackend:
    if RENDER_BACKEND == "cpu":
        surface = pygame.display.set_mode((width, height), DISPLAY_FLAGS)
        return CPUBackend(surface)
    if RENDER_BACKEND == "gpu":
        pygame.display.set_mode((width, height), pygame.OPENGL | pygame.DOUBLEBUF)
        return GPUBackend(width, height)
    raise ValueError(f"unknown RENDER_BACKEND {RENDER_BACKEND!r}")
