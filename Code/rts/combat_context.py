"""Minimal combat context for RTS tribe units spawned outside enemy spawner."""


def _noop(*_args, **_kwargs):
    return None


def make_rts_combat_context(world_adapter=None):
    level = getattr(world_adapter, "level", None) if world_adapter is not None else None
    update_quad_tree = None
    if world_adapter is not None and hasattr(world_adapter, "get_layout_callback_update_quad_tree"):
        update_quad_tree = world_adapter.get_layout_callback_update_quad_tree()
    ctx = {
        "level": level,
        "default_target": getattr(level, "player", None) if level is not None else None,
        "trigger_death_particles": _noop,
        "add_exp": _noop,
    }
    if update_quad_tree is not None:
        ctx["update_quad_tree"] = update_quad_tree
    return ctx
