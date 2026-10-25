"""The 60 clips the settled plan still owes, as one cells file per model.

Prompt tables come from mkcells.py by import, never by copy: the drift between the plan and the
run started with a second copy of these strings.

Gaps, against the agreed 374-clip table:
  C6   chaining PLUS the fitted constraint - the one C variant never generated  (3 cells)
  CW   chaining x wording as a real grid: drunk|heavy x the two best chain configs by measured
       peak (C2 long-action 187, C4 stance 176), x 3 actions                   (12 cells)
  W    the drunk arm of the wording sweep, at the same 4.0s no-constraint settings as the
       other three arms so the comparison is controlled                         (5 cells)
  B1b  the stale-constraint bug on the two actions it was never run on          (2 cells)
  M3   model rerun at 3 seeds, 2 models - one file per model, the driver loads one model
"""
import json
import runpy

m = runpy.run_path("/workspace/mkcells.py")
ORIG, HEAVY = m["ORIG"], m["HEAVY"]
C = "/workspace/cons"
THREE = ["haymaker", "groundsmash", "jump"]

READY = "A huge heavy brute stands ready. %s It returns to standing."
STANCE = "A huge heavy brute crouches low in a fighting stance. %s It settles back into the fighting stance."
CFG_CONFIG = {"C2": ("0.5 4.0 0.5", READY), "C4": ("1.0 2.5 1.0", STANCE)}

rest = []
for a in THREE:
    # C6: C1's wording and split, with the anchor fitted to its own 135 frames
    rest.append({"name": "C6_conschain_" + a, "prompt": READY % ORIG[a],
                 "duration": "1.0 2.5 1.0", "constraints": C + "/full_135.json"})
    for cfg, (dur, tmpl) in CFG_CONFIG.items():
        rest.append({"name": "CW_%s_drunk_%s" % (cfg, a), "prompt": tmpl % ORIG[a],
                     "duration": dur})
        rest.append({"name": "CW_%s_heavy_%s" % (cfg, a), "prompt": tmpl % HEAVY[a],
                     "duration": dur})

for a in ORIG:
    rest.append({"name": "W_drunk_" + a, "prompt": ORIG[a], "duration": "4.0"})

for a in ("jump", "damage"):
    rest.append({"name": "B1b_stale_8s_" + a, "prompt": ORIG[a], "duration": "8.0",
                 "constraints": C + "/full_150.json"})

json.dump(rest, open("/workspace/cells_rest.json", "w"), indent=1)
print("rest cells:", len(rest), " clips:", len(rest) * 2)

for tag, model in (("RPv1", "Kimodo-SOMA-RP-v1"), ("SEEDv11", "Kimodo-SOMA-SEED-v1.1")):
    cells = [{"name": "M3_%s_%s_s%d" % (tag, a, s), "prompt": ORIG[a], "duration": "4.0",
              "seed": s} for a in THREE for s in (11, 22, 33)]
    json.dump(cells, open("/workspace/cells_m3_%s.json" % tag, "w"), indent=1)
    print("m3 %-8s %s cells: %d  clips: %d" % (tag, model, len(cells), len(cells) * 2))
