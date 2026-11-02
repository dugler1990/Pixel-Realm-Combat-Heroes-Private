"""Helpers shared by the explode scripts (run inside the Blender venv)."""
import numpy as np


def fill_unwritten_texels(img, rings=24):
    """TRELLIS's bake leaves ~5 % of texels unwritten (black, alpha 0) inside the charts: dark speckle.
    Fill each from its written neighbours, growing `rings` texels."""
    W, H = img.size
    px = np.array(img.pixels[:], np.float32).reshape(H, W, 4)
    known = (px[..., 3] > 0) | (px[..., :3].max(2) > 0)
    col = px[..., :3] * known[..., None]
    for _ in range(rings):
        s = np.zeros_like(col); c = np.zeros((H, W))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                s += np.roll(np.roll(col * known[..., None], dy, 0), dx, 1)
                c += np.roll(np.roll(known, dy, 0), dx, 1)
        fill = (~known) & (c > 0)
        col[fill] = s[fill] / c[fill][:, None]
        known |= fill
    px[..., :3] = col
    px[..., 3] = 1
    img.pixels[:] = px.ravel()
    img.update()


def world_verts(o):
    co = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", co)
    m = np.array(o.matrix_world)
    return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def match_by_centre(done, shells, log=print):
    """HoloPart's export renames parts geometry_<i>: give each completed object the name of the shell
    whose bounding-box centre is nearest (greedy, one-to-one). done/shells: {name: object}."""
    bc = lambda o: (world_verts(o).min(0) + world_verts(o).max(0)) / 2
    sc = {n: bc(o) for n, o in shells.items()}
    pairs = sorted((float(np.linalg.norm(bc(o) - c)), dn, sn) for dn, o in done.items() for sn, c in sc.items())
    out, used = {}, set()
    for dist, dn, sn in pairs:
        if dn not in used and sn not in out:
            out[sn] = done[dn]; used.add(dn)
            log(f"{dn} -> {sn} (centre {dist:.4f} apart)")
    return out
