"""Paint an outfit (or the bare character) start to finish, the same way every time: one command.

    .venv-bpy/Scripts/python.exe paint_outfit.py <rigged.glb> <work_dir> <reference.png> [<roles.json> <look.json>] [--redo view ...]

--redo: also repaint these views even though they line up (a fault only an eye catches, e.g. the
armour's hand_l_out painted skin-coloured gaps between the fingers). Logged in <work_dir>/redo_log.txt.

e.g. (Boss repo root)
    paint_outfit.py generated\\bosses\\barb\\explode2\\fullplate\\fullplate_rigged.glb
                    generated\\bosses\\barb\\explode2\\fullplate\\paint generated\\bosses\\barb\\gear_test\\in\\barb_fullplate.png

1. views    only if <work_dir>/cams.json is missing (then roles.json and look.json are needed; give
            roles.json anyway: project then keeps each close-up to its own body region)
2. gen      "missing": every view without a usable painting (none yet, or one that does not line up
            with the model). Each painting is checked as it arrives with project's own alignment rule
            and repainted up to 2 more times; the look decides the model (provider/model/quality).
3. project  the paintings onto the model -> <work_dir>/result/ (a painting that still does not line
            up is dropped there and listed in result/patches/patches.json)
4. diag     explode2/diag.py on the outfit folder (the parent of <work_dir>) -> DIAGNOSTICS.md
Re-running it repaints only what is missing or unusable, then projects again. Stops at the first step
that fails. Keys from the environment: LEONARDO_API_KEY or OPENAI_API_KEY (the look's provider).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
argv, redo = sys.argv[1:], []
if "--redo" in argv:
    i = argv.index("--redo")
    argv, redo = argv[:i], argv[i + 1:]
glb, work, ref = (os.path.abspath(a) for a in argv[:3])
extra = [os.path.abspath(a) for a in argv[3:]]
REPAINT = os.path.join(HERE, "repaint.py")
if redo:
    with open(os.path.join(work, "redo_log.txt"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M')} redo by eye: {' '.join(redo)}\n")


def step(name, args):
    print(f"=== {name}", flush=True)
    r = subprocess.run([sys.executable] + args)
    if r.returncode:
        sys.exit(f"STOPPED at {name} (exit {r.returncode})")


if not os.path.isfile(os.path.join(work, "cams.json")):
    if len(extra) != 2:
        sys.exit("no cams.json yet: give <roles.json> <look.json> so the views can be rendered first")
    step("views", [REPAINT, "views", glb, work, extra[0], "--look", extra[1]])
step("gen", [REPAINT, "gen", work, ref, "missing"] + redo)
# with the roles, each close-up paints only its own region (repaint.py project, REGION_BONES)
step("project", [REPAINT, "project", glb, work] + extra[:1])
step("diag", [os.path.join(HERE, "..", "explode2", "diag.py"), os.path.dirname(work)])
print("PAINT_OUTFIT_DONE", flush=True)
