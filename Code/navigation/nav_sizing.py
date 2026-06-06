"""Nav grid cell/probe sizing from unit sprite footprint."""


def nav_grid_params(unit_width, unit_height, margin_ratio=0.0):
    """Return (cell_w, cell_h, probe_w, probe_h) in world pixels from unit bbox."""
    w = max(4, int(unit_width))
    h = max(4, int(unit_height))
    if margin_ratio:
        w = max(4, int(w * (1 + margin_ratio)))
        h = max(4, int(h * (1 + margin_ratio)))
    return w, h, w, h
