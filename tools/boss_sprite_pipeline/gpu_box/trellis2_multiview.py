"""Several views (front, back, optional sides and 3/4 views) into ONE TRELLIS.2 generation, on stock microsoft/TRELLIS.2.

At every sampling step of the sparse-structure and shape stages, each view predicts the update for the whole latent
from its own image; the predictions are blended per voxel by where the voxel sits: the front half follows the front
image, the back half the back image, with a smooth band at the middle. One shared latent, so no seam to stitch.

Ported from visualbruno/ComfyUI-Trellis2 (MIT, commit b0e84c0: FlowEulerMultiViewSampler, run_multiview) with two
changes, both checked against the stock code (explode2/PROCESS_explode2.md, 2026-11-07):
- axis: stock voxel coords are (x, y, z) = (D, H, W) and our meshes face -y, so front = -y, back = +y, his right =
  -x, left = +x. The pack blends along x or z only (`front_axis`), never y.
- band: weights are softmax(score / BAND) with score = signed position in object units (cube [-0.5, 0.5]). The pack's
  softmax(2 * pos[-1, 1]) gives the front image only ~70 % at the chest surface of a body ~0.2 deep (near plain
  averaging, the reported fat / thin drift). BAND 0.03 gives ~96 % at the surface, 50 / 50 only at the mid-plane.
The texture stage is not blended (front view only): we keep geometry and paint it ourselves (--skip-texture).
"""
import math

import torch
from easydict import EasyDict as edict

from trellis2.pipelines.samplers.flow_euler import FlowEulerGuidanceIntervalSampler, FlowEulerSampler

# Where each view's camera stands, as a unit vector in (x, y): front = -y, back = +y, his right = -x, left = +x;
# the 3/4 views halfway between. A voxel follows the view it faces most: score = direction . position / band.
# (front / back / right / left give the same scores as the earlier (axis, sign) table.)
_H = 0.5 ** 0.5
DIRS = {"front": (0.0, -1.0), "back": (0.0, 1.0), "right": (-1.0, 0.0), "left": (1.0, 0.0),
        "front_left": (_H, -_H), "front_right": (-_H, -_H), "back_left": (_H, _H), "back_right": (-_H, _H)}
VIEWS = tuple(DIRS)


def _positions(x_t):
    """Voxel centres in object units: (x, y) broadcastable to the prediction (dense) or (N, 1) (sparse)."""
    if isinstance(x_t, torch.Tensor):                       # dense (B, C, D, H, W), D = x, H = y
        D, H = x_t.shape[2], x_t.shape[3]
        x = ((torch.arange(D, device=x_t.device) + 0.5) / D - 0.5).view(1, 1, D, 1, 1)
        y = ((torch.arange(H, device=x_t.device) + 0.5) / H - 0.5).view(1, 1, 1, H, 1)
        return x, y
    c = x_t.coords[:, 1:].float()                           # sparse: grid size = next power of two over the extent
    R = 2 ** math.ceil(math.log2(float(c.max()) + 1))
    return ((c[:, 0:1] + 0.5) / R - 0.5), ((c[:, 1:2] + 0.5) / R - 0.5)


class MultiViewSampler(FlowEulerGuidanceIntervalSampler):
    """Drop-in for the pipeline's guidance-interval Euler sampler. `sets` maps id(front cond tensor) -> {view: cond
    dict}, so the same sampler serves the 512 and 1024 stages (the pipeline passes the front view's cond)."""

    def __init__(self, base, views, sets, band):
        FlowEulerSampler.__init__(self, base.sigma_min)
        self.views, self.sets, self.band = views, sets, band

    def _weights(self, x_t):
        x, y = _positions(x_t)
        scores = torch.broadcast_tensors(*[(DIRS[v][0] * x + DIRS[v][1] * y) / self.band for v in self.views])
        return torch.softmax(torch.stack(scores, -1), -1).unbind(-1)

    @torch.no_grad()
    def sample_once(self, model, x_t, t, t_prev, cond=None, **kwargs):
        conds = self.sets[id(cond)]
        sparse = not isinstance(x_t, torch.Tensor)
        acc = None
        for name, w in zip(self.views, self._weights(x_t)):
            kw = dict(kwargs)
            kw["neg_cond"] = conds[name]["neg_cond"]
            pv = self._inference_model(model, x_t, t, conds[name]["cond"], **kw)
            part = (pv.feats if sparse else pv) * w
            acc = part if acc is None else acc + part
        v = x_t.replace(acc) if sparse else acc
        x0, _ = self._v_to_xstart_eps(x_t=x_t, t=t, v=v)
        return edict({"pred_x_prev": x_t - (t - t_prev) * v, "pred_x_0": x0})


@torch.no_grad()
def run_multiview(pipeline, images, seed=0, band=0.03, max_num_tokens=49152):
    """images: {'front': PIL, 'back': PIL, ...} (front required). 1024_cascade, as trellis2_run.py. Returns the mesh."""
    views = [v for v in VIEWS if v in images]
    imgs = {v: pipeline.preprocess_image(images[v]) for v in views}
    torch.manual_seed(seed)
    c512 = {v: pipeline.get_cond([imgs[v]], 512) for v in views}
    c1024 = {v: pipeline.get_cond([imgs[v]], 1024) for v in views}
    sets = {id(c512["front"]["cond"]): c512, id(c1024["front"]["cond"]): c1024}
    ss, sh = pipeline.sparse_structure_sampler, pipeline.shape_slat_sampler
    pipeline.sparse_structure_sampler = MultiViewSampler(ss, views, sets, band)
    pipeline.shape_slat_sampler = MultiViewSampler(sh, views, sets, band)
    try:
        coords = pipeline.sample_sparse_structure(c512["front"], 32, 1, {})
        shape_slat, res = pipeline.sample_shape_slat_cascade(
            c512["front"], c1024["front"],
            pipeline.models["shape_slat_flow_model_512"], pipeline.models["shape_slat_flow_model_1024"],
            512, 1024, coords, {}, max_num_tokens)
    finally:
        pipeline.sparse_structure_sampler, pipeline.shape_slat_sampler = ss, sh
    tex_slat = pipeline.sample_tex_slat(c1024["front"], pipeline.models["tex_slat_flow_model_1024"], shape_slat, {})
    torch.cuda.empty_cache()
    return pipeline.decode_latent(shape_slat, tex_slat, res)[0]
