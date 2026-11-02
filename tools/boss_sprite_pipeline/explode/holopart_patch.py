"""Patch a fresh HoloPart clone (VAST-AI-Research/HoloPart @ 48dd632) for the explode pipeline.

    python holopart_patch.py <HoloPart dir>

- HP_FACES (default 150000): faces per part after decimation (upstream hard-codes 10,000).
- Before decimating: Taubin smoothing (HP_SMOOTH steps, default 10) removes the voxel stair-steps
  the flash decoder leaves, then holes up to HP_HOLE edges (default 60) are closed (pinholes).
- Seeds numpy so the surface sampling (and so each part's centre/scale) is repeatable.
- Saves the latents (HP_LATENTS) so the meshes can be re-extracted without re-running diffusion.
- holopart/inference_utils.py: optional HP_BLUR (voxels) blurs the logit grid before meshing.
  Tried 2026-11-01: it removes thin plates before it removes the steps — leave it off.
"""
import sys
from pathlib import Path

p = Path(sys.argv[1]) / "scripts" / "inference_holopart.py"
s = p.read_text()
EDITS = [
    ("NUM_SURFACE_SAMPLES = 20480\n",
     "NUM_SURFACE_SAMPLES = 20480\nnp.random.seed(0)\n"),
    ("    ms.meshing_merge_close_vertices()\n",
     "    ms.meshing_merge_close_vertices()\n"
     "    ms.apply_coord_taubin_smoothing(lambda_=0.5, mu=-0.53, stepsmoothnum=int(os.environ.get(\"HP_SMOOTH\", \"10\")))\n"
     "    try:\n"
     "        ms.meshing_repair_non_manifold_edges()\n"
     "        ms.meshing_close_holes(maxholesize=int(os.environ.get(\"HP_HOLE\", \"60\")))\n"
     "    except Exception as e:\n"
     "        print(\"close holes skipped:\", e)\n"),
    ("    meshes_latent = torch.cat(latent_list, dim=0)\n",
     "    meshes_latent = torch.cat(latent_list, dim=0)\n"
     "    torch.save(meshes_latent.cpu(), os.environ.get(\"HP_LATENTS\", \"latents.pt\"))\n"),
    ("part_mesh = simplify_mesh(part_mesh, 10000)",
     "part_mesh = simplify_mesh(part_mesh, int(os.environ.get(\"HP_FACES\", \"150000\")))"),
]
for old, new in EDITS:
    assert s.count(old) == 1, f"patch target not found once: {old!r}"
    s = s.replace(old, new)
p.write_text(s)
print("PATCHED", p)

# The decoded occupancy is close to on/off at the voxel scale (fp32 decoding gives the same stair-steps
# as fp16), so marching cubes snaps to the grid. HP_BLUR = Gaussian sigma in voxels applied to the
# final logit grid before meshing (NaN cells = not evaluated: normalised convolution skips them).
p = Path(sys.argv[1]) / "holopart" / "inference_utils.py"
s = p.read_text()
old = "    grid_logits = grid_logits[0]\n    try:\n        print(\"final grids shape = \", grid_logits.shape)\n        dmc = DiffDMC"
assert s.count(old) == 1, "flash extract target not found once"
s = s.replace(old, old.replace("    grid_logits = grid_logits[0]\n",
                               "    grid_logits = grid_logits[0]\n"
                               "    if float(os.environ.get(\"HP_BLUR\", \"0\")) > 0:\n"
                               "        grid_logits = nan_gaussian_blur(grid_logits, float(os.environ[\"HP_BLUR\"]))\n"))
s = "import os\n" + s + '''

def nan_gaussian_blur(g, sigma):
    r = int(3 * sigma + 0.999)
    x = torch.arange(-r, r + 1, device=g.device, dtype=torch.float32)
    k = torch.exp(-x ** 2 / (2 * sigma ** 2))
    k = k / k.sum()
    m = (~torch.isnan(g)).float()[None, None]
    v = torch.nan_to_num(g.float())[None, None] * m
    for d in range(3):                       # separable: D, H, W
        shape = [1, 1, 1, 1, 1]
        shape[2 + d] = 2 * r + 1
        pad = [0] * 6
        pad[2 * (2 - d)] = pad[2 * (2 - d) + 1] = r
        v = torch.nn.functional.conv3d(torch.nn.functional.pad(v, pad), k.view(shape))
        m = torch.nn.functional.conv3d(torch.nn.functional.pad(m, pad), k.view(shape))
    out = (v / m.clamp_min(1e-6))[0, 0]
    out[m[0, 0] < 1e-3] = float("nan")
    return out
'''
p.write_text(s)
print("PATCHED", p)
