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


def test_poses(roles):
    """The pose test's poses (explode_pose.py) and the fit's (explode2/options/fit_piece.py): name -> [(bone, axis, deg)]."""
    al, ar, ll, lr = roles["arm_l"], roles["arm_r"], roles["leg_l"], roles["leg_r"]
    return {
        "rest": [],
        "arms up": [(al["elbow"], "Y", -70), (ar["elbow"], "Y", 70)],
        "arms fwd": [(al["elbow"], "X", -70), (ar["elbow"], "X", -70)],
        "twist": [(roles["chest"], "Z", 35)],
        "bend": [(roles["spine"], "X", 30)],
        "step": [(ll["hip"], "X", -40), (ll["knee"], "X", 50), (lr["hip"], "X", 25)],
    }


PAULDRON_ARM = 0.75     # the pauldron's share of the upper arm (rest: the collarbone); fit_set.json records it


def piece_weights(part, P, Wa, roles, gnames, h, pauldron_arm=PAULDRON_ARM):
    """Plate armour weights for one piece (explode_pose --rigid, explode2/options/fit_set.py): each piece moves with
    fixed bones, not with the skin under it. P: the piece's vertices (world, rest); Wa: the body weights
    copied to them (nearest body vertices), columns = gnames; h: figure height; pauldron_arm: as the fit used."""
    import numpy as np
    base, side = (part[:-2], part[-1]) if part[-2:] in ("_l", "_r") else (part, None)
    arm_r, leg_r = (roles.get(f"arm_{side}"), roles.get(f"leg_{side}")) if side else (None, None)
    gi = gnames.index
    out = np.zeros_like(Wa)
    if base in ("head", "torso", "belt"):                       # one bone, 100 %
        out[:, gi(roles[{"head": "head", "torso": "chest", "belt": "root"}[base]])] = 1
    elif base == "pauldron":                                     # rides mostly with the upper arm, as strapped plate
        out[:, gi(arm_r["shoulder"])] = 1 - pauldron_arm         # does (halfway left the deltoid bare with the arms
        out[:, gi(arm_r["elbow"])] = pauldron_arm                # up / swung, 2026-11-04)
    elif base in ("skirt", "loincloth"):                          # hips at the waist, up to 50 % thigh at the hem
        z = P[:, 2]
        t = 0.5 * np.clip((z.max() - z) / max(np.ptp(z), 1e-9), 0, 1)
        sl = 1 / (1 + np.exp(-P[:, 0] / (0.02 * h)))               # +x = his left
        out[:, gi(roles["root"])] = 1 - t
        out[:, gi(roles["leg_l"]["hip"])] += t * sl
        out[:, gi(roles["leg_r"]["hip"])] += t * (1 - sl)
    else:                                                        # each plate follows the one bone it sits on
        allowed = {"arm": [arm_r["elbow"], arm_r["wrist"]], "gauntlet": [arm_r["wrist"], arm_r["hand"]],
                   "leg": [leg_r["hip"], leg_r["knee"]], "boot": [leg_r["ankle"], leg_r["foot"]]}[base]
        cols = [gi(b) for b in allowed]
        pick = np.array(cols)[np.argmax(Wa[:, cols], 1)]
        out[np.arange(len(P)), pick] = 1
    return out


def skin_bones(part, roles):
    """The bones whose skin a worn piece covers: only skin on these is tucked / hidden under it. The torso
    must not take the upper arms: their skin by the arm hole fills the armpit when the arm lifts (taken from
    the copied skin it held bone_7 / bone_14 and tore the armpits, 2026-11-02)."""
    base, side = (part[:-2], part[-1]) if part[-2:] in ("_l", "_r") else (part, None)
    a, l = (roles.get(f"arm_{side}"), roles.get(f"leg_{side}")) if side else (None, None)
    return {
        "torso": [roles[k] for k in ("root", "spine", "spine2", "chest", "neck")]
                 + [roles["arm_l"]["shoulder"], roles["arm_r"]["shoulder"]],
        "belt": [roles["root"], roles["spine"]],
        "skirt": [roles["root"], roles["leg_l"]["hip"], roles["leg_r"]["hip"]],
        "loincloth": [roles["root"], roles["leg_l"]["hip"], roles["leg_r"]["hip"]],
        "head": [roles["neck"], roles["head"]],
        "pauldron": [a["shoulder"], a["elbow"]] if a else [],
        "arm": [a["elbow"], a["wrist"]] if a else [],
        "gauntlet": [a["wrist"], a["hand"]] if a else [],
        "leg": [l["hip"], l["knee"]] if l else [],
        "boot": [l["ankle"], l["foot"]] if l else [],
    }.get(base, [])


def stretch_poses(roles):
    """The most-stretched positions the clips reach (two-hand swing, overhead chop): fit_piece.py and
    explode_pose.py --tuck use these with test_poses, so a piece clears the body, and the tucked skin stays
    under it, at the extremes and not only in the 6 test poses. Same form: name -> [(bone, axis, deg)],
    applied in order about each bone's head in world space."""
    al, ar = roles["arm_l"], roles["arm_r"]
    ch, sp = roles["chest"], roles["spine"]
    return {
        "arms overhead": [(al["elbow"], "Y", -150), (ar["elbow"], "Y", 150)],
        "arms back": [(al["elbow"], "X", 60), (ar["elbow"], "X", 60)],
        "arms across": [(al["elbow"], "X", -90), (ar["elbow"], "X", -90), (al["elbow"], "Z", -40), (ar["elbow"], "Z", 40)],
        "swing back": [(ch, "Z", -45), (al["elbow"], "Y", -90), (ar["elbow"], "Y", 90),
                       (al["elbow"], "X", 40), (ar["elbow"], "X", 40)],
        "swing fwd": [(ch, "Z", 45), (al["elbow"], "X", -90), (ar["elbow"], "X", -90)],
        "back arch": [(sp, "X", -20)],
        "side bend l": [(sp, "Y", -25)],
        "side bend r": [(sp, "Y", 25)],
    }


def fit_poses(roles):
    """Every pose a piece must clear and keep the skin under: the test poses and the stretch poses."""
    return {**test_poses(roles), **stretch_poses(roles)}


def set_pose(arm, rots):
    """Rest, then each (bone, axis, deg) rotated about the bone's head in world space, in order."""
    import math
    from mathutils import Matrix
    import bpy
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    M = arm.matrix_world
    for bone, axis, deg in rots:
        pb = arm.pose.bones[bone]
        h = M @ pb.head
        R = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-h)
        pb.matrix = M.inverted() @ R @ M @ pb.matrix
        bpy.context.view_layer.update()


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
