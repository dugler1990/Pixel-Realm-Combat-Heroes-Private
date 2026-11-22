"""Visible ice-fog debug playground.

Not part of a normal pytest run. Circle, pads, teleports, and wind whisper on screen.

    pytest tests/test_ice_fog_play.py

Controls: arrows move, Esc quit, 1 wrap fixture, 2 sequence, 3 pads, Space dismiss whisper.
"""

import math
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ice_fog"


def test_ice_fog_visible_playground(request):
    invoked = request.config.invocation_params.args
    if not any("test_ice_fog_play.py" in str(arg) for arg in invoked):
        pytest.skip("opens a window; run pytest tests/test_ice_fog_play.py")

    for key in ("SDL_VIDEODRIVER", "SDL_AUDIODRIVER"):
        os.environ.pop(key, None)
    if str(CODE_DIR) not in sys.path:
        sys.path.insert(0, str(CODE_DIR))

    import pygame
    from dialogue.session import DialogueSession
    from ice_fog.config import load_ordeal_config
    from ice_fog.ordeal import FogOrdeal

    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Ice fog playground")
    clock = pygame.time.Clock()

    class _Backend:
        def get_size(self):
            return screen.get_size()

        def draw_rect(self, color, rect, width=0):
            pygame.draw.rect(screen, color, rect, width)

        def blit(self, surface, dest, **kwargs):
            screen.blit(surface, dest)

        def invalidate_texture(self, surface):
            return None

    fixtures = {
        pygame.K_1: FIXTURES / "ordeal_wrap.json",
        pygame.K_2: FIXTURES / "ordeal_sequence.json",
        pygame.K_3: FIXTURES / "ordeal_pads.json",
    }
    path = FIXTURES / "ordeal_wrap.json"
    ordeal = FogOrdeal(load_ordeal_config(path))
    session = DialogueSession()
    backend = _Backend()
    px, py = float(ordeal.circle.cx), float(ordeal.circle.cy - 40)
    speed = 180.0
    last_chord = None
    font = pygame.font.Font(None, 22)
    running = True
    print(
        "\nIce fog playground: circle on screen.\n"
        "Arrows move. 1=wrap 2=sequence 3=pads. Esc quits.\n",
        flush=True,
    )

    while running:
        dt_ms = clock.tick(60)
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if session.whisper_active():
                        session.clear_whisper()
                    else:
                        running = False
                elif event.key in fixtures:
                    path = fixtures[event.key]
                    ordeal = FogOrdeal(load_ordeal_config(path))
                    px, py = float(ordeal.circle.cx), float(ordeal.circle.cy - 40)
                    last_chord = None
                elif event.key == pygame.K_SPACE:
                    session.handle_input(
                        type("K", (), {"is_key_just_pressed": lambda self, k: k == pygame.K_SPACE})()
                    )

        keys = pygame.key.get_pressed()
        dx = dy = 0.0
        if keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_RIGHT]:
            dx += 1
        if keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_DOWN]:
            dy += 1
        if dx or dy:
            length = math.hypot(dx, dy) or 1.0
            px += dx / length * speed * (dt_ms / 1000.0)
            py += dy / length * speed * (dt_ms / 1000.0)

        events = ordeal.update_position(px, py, now_ms=now)
        px, py = ordeal.position()
        for ev in events:
            if ev["type"] == "teleported":
                last_chord = (ev["from"], ev["to"])
            if ev["type"] == "whisper":
                session.push_whisper_line(ev["line_id"], now)
        session._tick_whisper(now)

        screen.fill((24, 28, 36))
        c = ordeal.circle
        pygame.draw.circle(screen, (80, 140, 200), (int(c.cx), int(c.cy)), int(c.r), 2)
        pygame.draw.circle(screen, (120, 180, 220), (int(c.cx), int(c.cy)), 3)
        if ordeal.pads is not None:
            for pad in ordeal.pads.pads:
                ang = math.radians(pad.angle_deg)
                # angle 0 = east, CCW with y-up for math; screen y down → negate sin
                hx = c.cx + math.cos(ang) * (c.r - 4)
                hy = c.cy - math.sin(ang) * (c.r - 4)
                pygame.draw.circle(screen, (220, 180, 80), (int(hx), int(hy)), 8)
                label = font.render(pad.pad_id, True, (240, 220, 160))
                screen.blit(label, (hx + 6, hy - 8))
        if last_chord is not None:
            (fx, fy), (tx, ty) = last_chord
            pygame.draw.line(
                screen, (200, 100, 120), (int(fx), int(fy)), (int(tx), int(ty)), 2
            )
        color = (220, 80, 80) if ordeal.tangled else (180, 220, 180)
        pygame.draw.circle(screen, color, (int(px), int(py)), 7)
        status = font.render(
            f"{path.name}  tangled={ordeal.tangled}  steps={ordeal.path.steps}",
            True,
            (220, 220, 220),
        )
        screen.blit(status, (12, 12))
        hint = font.render("1 wrap  2 sequence  3 pads  arrows move  Esc quit", True, (160, 160, 160))
        screen.blit(hint, (12, 36))
        session.draw(backend, type("O", (), {"x": 0, "y": 0})())
        pygame.display.flip()

    pygame.quit()
