from navigation.nav_sizing import nav_grid_params


def test_nav_grid_params_worker_eskimo_footprint():
    cell_w, cell_h, probe_w, probe_h = nav_grid_params(16, 24)
    assert (cell_w, cell_h, probe_w, probe_h) == (16, 24, 16, 24)


def test_nav_grid_params_cell_matches_probe():
    cell_w, cell_h, probe_w, probe_h = nav_grid_params(16, 24)
    assert cell_w == probe_w
    assert cell_h == probe_h


def test_nav_grid_params_cell_at_least_four():
    cell_w, cell_h, probe_w, probe_h = nav_grid_params(2, 2)
    assert cell_w >= 4
    assert cell_h >= 4
    assert probe_w == cell_w
    assert probe_h == cell_h
