import pygame

from rts.session import RtsSession
from rts.world_sim import RtsWorldSim

from fakes import FakeInputManager, FakeSprite, FakeWorldAdapter


def make_session(selectables=None, player=None):
    world = FakeWorldAdapter(player=player, selectables=selectables or [])
    input_manager = FakeInputManager()
    world_sim = RtsWorldSim()
    session = RtsSession(world, input_manager, world_sim)
    return session, world, input_manager, world_sim


def test_enter_sets_camera_state_throne_and_refreshes_selectables():
    throne = FakeSprite(center=(200, 150), kind="seat", profile_id="throne_royal")
    other = FakeSprite(center=(300, 150), kind="rts_building")
    session, world, _, _ = make_session([throne, other])

    session.enter(throne)

    assert session.is_active()
    assert session.state == RtsSession.CAMERA
    assert session.throne is throne
    assert session.camera.rect.center == throne.rect.center
    assert [item.sprite for item in session.selection.selectables] == [throne, other]
    assert not world.stand_requested


def test_camera_focus_uses_player_when_inactive_and_camera_when_active():
    player = FakeSprite(center=(80, 90), kind="player")
    throne = FakeSprite(center=(250, 260), kind="seat")
    session, _, _, _ = make_session([throne], player=player)

    assert session.camera_focus() is player

    session.enter(throne)

    assert session.camera_focus() is session.camera


def test_space_exits_and_requests_player_stand():
    throne = FakeSprite(center=(200, 150), kind="seat")
    session, world, input_manager, world_sim = make_session([throne])
    worker = FakeSprite(center=(100, 100), kind="rts_unit")
    worker.faction_id = "eskimo_tribe"
    world_sim.gather_controller.tasks[id(worker)] = worker
    session.enter(throne)

    input_manager.press(pygame.K_SPACE)
    session.update(0.016)

    assert not session.is_active()
    assert session.state == RtsSession.INACTIVE
    assert world.stand_requested
    assert session.throne is None
    assert id(worker) in world_sim.gather_controller.tasks


def test_home_snaps_camera_back_to_throne():
    throne = FakeSprite(center=(200, 150), kind="seat")
    session, _, input_manager, _ = make_session([throne])
    session.enter(throne)
    session.camera.snap_to((700, 700))

    input_manager.press(pygame.K_HOME)
    session.update(0.016)

    assert session.camera.rect.center == throne.rect.center


def test_tab_enters_selection_and_selects_bottom_left():
    upper = FakeSprite(center=(100, 80), kind="seat")
    bottom_left = FakeSprite(center=(50, 250), kind="rts_building")
    bottom_right = FakeSprite(center=(200, 250), kind="rts_building")
    session, _, input_manager, _ = make_session([upper, bottom_right, bottom_left])
    session.enter(upper)

    input_manager.press(pygame.K_TAB)
    session.update(0.016)

    assert session.state == RtsSession.SELECT
    assert session.selection.selected.sprite is bottom_left


def test_enter_opens_panel_only_when_selection_exists():
    session, _, input_manager, _ = make_session([])
    session.enter()

    input_manager.press(pygame.K_TAB)
    session.update(0.016)
    input_manager.clear_just_pressed()

    assert session.state == RtsSession.SELECT
    assert session.selection.selected is None

    input_manager.press(pygame.K_RETURN)
    session.update(0.016)

    assert session.state == RtsSession.SELECT

    selectable = FakeSprite(center=(50, 200), kind="seat")
    session.world.selectables = [selectable]
    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_TAB)
    session.update(0.016)
    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_TAB)
    session.update(0.016)
    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_RETURN)
    session.update(0.016)

    assert session.state == RtsSession.PANEL


def test_escape_and_tab_back_out_of_panel_and_select_states():
    selectable = FakeSprite(center=(50, 200), kind="seat")
    session, _, input_manager, _ = make_session([selectable])
    session.enter(selectable)

    input_manager.press(pygame.K_TAB)
    session.update(0.016)
    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_RETURN)
    session.update(0.016)

    assert session.state == RtsSession.PANEL

    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_ESCAPE)
    session.update(0.016)

    assert session.state == RtsSession.SELECT

    input_manager.clear_just_pressed()
    input_manager.press(pygame.K_TAB)
    session.update(0.016)

    assert session.state == RtsSession.CAMERA
    assert session.selection.selected is None


def test_player_death_deactivates_without_requesting_stand():
    throne = FakeSprite(center=(200, 150), kind="seat")
    session, world, _, _ = make_session([throne])
    session.enter(throne)
    world.player_dead = True

    session.update(0.016)

    assert not session.is_active()
    assert session.state == RtsSession.INACTIVE
    assert not world.stand_requested
