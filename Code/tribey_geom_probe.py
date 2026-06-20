"""TEMP probe: load tribey_spear through the REAL Enemy loading + animate path and
dump, per frame, where the feet land relative to the hitbox and the on-disk asset.
No rendering. Run: SDL_VIDEODRIVER=dummy python3 tribey_geom_probe.py
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
pygame.display.init()
pygame.display.set_mode((1, 1))

from types import SimpleNamespace
from Enemy import Enemy
from Support import get_or_build_entity_masks, import_folder

NAME = "tribey_spear"
POS = (100, 100)


def feet_row(img):
    rects = pygame.mask.from_surface(img).get_bounding_rects()
    return max((r.bottom for r in rects), default=img.get_height())


def disk_feet_row(status, i):
    folder = f"../Graphics/Monsters/{NAME}/{status}"
    files = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
    img = pygame.image.load(os.path.join(folder, files[i])).convert_alpha()
    return img.get_size(), feet_row(img)


# --- build a stub and run the REAL loading code on it ---
stub = SimpleNamespace()
Enemy.import_graphics_left_right(stub, NAME)
stub.animations_left_right_indicator = True
stub.masks = get_or_build_entity_masks(NAME, stub.animations, True, skip_disk=False)
stub.get_direction_as_string = lambda: "right"
stub.wave_value = lambda: 255
stub.vulnerable = True
stub.frozen = False
stub.animation_speed = 0.0          # hold frame_index so we can step manually
stub.status = "idle"
stub.frame_index = 0

# spawn geometry exactly like Enemy.__init__
stub.image = stub.animations["idle"]["right"][0]
stub.rect = stub.image.get_rect(topleft=POS)
stub.hitbox = stub.rect.inflate(0, -10)
print(f"SPAWN: idle[0] img={stub.image.get_size()} rect={tuple(stub.rect)} "
      f"hitbox=(t{stub.hitbox.top} b{stub.hitbox.bottom} cy{stub.hitbox.centery})\n")

print(f"{'status':7} {'fr':2} {'img':9} {'live_feet':9} {'disk':12} "
      f"{'rect.top':8} {'feet_world':10} {'hitbox.b':8} {'feet-hbox.b':11} {'shadow_old(rect.b)':18}")
for status in ("idle", "move", "attack"):
    n = len(stub.animations[status]["right"])
    for i in range(n):
        stub.status = status
        stub.frame_index = i
        Enemy.animate(stub)                       # REAL animate
        fw = stub.rect.top + feet_row(stub.image)
        dsize, dfeet = disk_feet_row(status, i)
        print(f"{status:7} {i:2} {str(stub.image.get_size()):9} "
              f"{feet_row(stub.image):9} {str(dsize)+'/'+str(dfeet):12} "
              f"{stub.rect.top:8} {fw:10} {stub.hitbox.bottom:8} "
              f"{fw - stub.hitbox.bottom:11} {stub.rect.bottom:18}")
