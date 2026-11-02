"""Re-mesh saved HoloPart latents with other decoder settings, no diffusion re-run (pod, HoloPart dir).

    python holopart_redecode.py <input_parts.glb> <latents.pt> <out.glb> <dtype fp16|fp32> <octree depth> [part idx,...]

Decodes each latent with the flash decoder at the given precision and grid depth (9 = 512^3 as
upstream, 10 = 1024^3), puts it back at its part's place and writes the raw marching-cubes meshes (no
decimation, no smoothing) as one GLB with the part names kept.
Part centre/scale come from a fresh prepare_data(): its surface sampling is random, so they differ
from the generating run by the bbox jitter of 20,480 samples (well under 1 % of the part).
"""
import os
import sys
import time

import numpy as np
import torch
import trimesh

sys.path.insert(0, os.getcwd())
from scripts.inference_holopart import prepare_data  # noqa: E402
from holopart.pipelines.pipeline_holopart import HoloPartPipeline  # noqa: E402
from holopart.inference_utils import flash_extract_geometry  # noqa: E402

GLB, LAT, OUT, DT, DEPTH = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
dtype = {"fp16": torch.float16, "fp32": torch.float32}[DT]
pipe = HoloPartPipeline.from_pretrained("pretrained_weights/HoloPart").to("cuda", dtype)
pipe.vae.set_flash_decoder()
batch = prepare_data(GLB, device="cuda")
latents = torch.load(LAT).to("cuda", dtype)
idx = [int(i) for i in sys.argv[6].split(",")] if len(sys.argv) > 6 else range(len(latents))
scene = trimesh.Scene()
for i in idx:
    t = time.time()
    with torch.no_grad():
        out = flash_extract_geometry(latents[i:i + 1], pipe.vae, bounds=(-1.05, -1.05, -1.05, 1.05, 1.05, 1.05),
                                     octree_depth=DEPTH, num_chunks=10000)
    m = trimesh.util.concatenate([trimesh.Trimesh(v.astype(np.float32), f) for v, f in out])
    m.apply_scale(batch["part_scale_list"][i])
    m.apply_translation(batch["part_center_list"][i].numpy())
    name = batch["part_id_list"][i]
    scene.add_geometry(m, node_name=name, geom_name=name)
    print(f"{name} {DT} depth {DEPTH}: {len(m.faces)} faces, {time.time() - t:.0f} s", flush=True)
    torch.cuda.empty_cache()
scene.export(OUT)
print("REDECODE_OK", OUT, flush=True)
