import pygame

from rts.visual_sequence import (
    FrameCycler,
    LayeredAmountVisual,
    TimedPhaseVisual,
    load_folder_frames,
)


def _fake_frames(n=3, size=(8, 8)):
    return [pygame.Surface(size) for _ in range(n)]


def test_frame_cycler_advances():
    pygame.init()
    cycler = FrameCycler(_fake_frames(4), frame_interval_sec=0.1)
    assert cycler._frame_index == 0
    cycler.update(0.25)
    assert cycler._frame_index == 2


def test_timed_phase_visual_completes_after_total_duration(monkeypatch):
    pygame.init()
    monkeypatch.setattr(
        "rts.visual_sequence.load_folder_frames",
        lambda *a, **k: _fake_frames(2),
    )
    phases = [
        {"folder": "p0", "durationSec": 1.0, "frameIntervalSec": 0.5},
        {"folder": "p1", "durationSec": 2.0, "frameIntervalSec": 0.5},
        {"folder": "p2", "durationSec": 1.0, "frameIntervalSec": 0.5},
        {"folder": "p3", "durationSec": 2.0, "frameIntervalSec": 0.5},
    ]
    visual = TimedPhaseVisual(phases)
    visual.start()
    visual.update(6.0)
    assert visual.is_complete()
    assert visual.phase_index == 4


def test_layered_amount_visual_drains_layers(monkeypatch):
    pygame.init()
    folders = []

    def _load(folder, sprite_keys=None, fallback_size=(32, 32)):
        folders.append(folder)
        return _fake_frames(1)

    monkeypatch.setattr("rts.visual_sequence.load_folder_frames", _load)
    layers = [
        {"iceCapacity": 25, "folder": "layer_0"},
        {"iceCapacity": 25, "folder": "layer_1"},
        {"iceCapacity": 25, "folder": "layer_2"},
        {"iceCapacity": 25, "folder": "layer_3"},
    ]
    visual = LayeredAmountVisual(layers, max_ice=100)
    assert visual.layer_index == 0
    for i in range(4):
        visual.drain(25)
        assert visual.ice_remaining == 100 - 25 * (i + 1)
    assert visual.is_depleted()
    assert visual.layer_index >= 4
    assert "layer_3" in folders


def test_load_folder_frames_fallback_sprite_keys(monkeypatch, tmp_path):
    pygame.init()
    monkeypatch.setattr(
        "rts.visual_sequence.rts_graphics_root",
        lambda: str(tmp_path),
    )
    frames = load_folder_frames("missing", sprite_keys=["node_ice_shelf"])
    assert len(frames) >= 1
