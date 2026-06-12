"""
JSON-driven debug log channels. See debug_logging.schema.md.
Call setup_debug_logging() once at process start (Main2 imports this first).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

_CODE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILENAME = "debug_logging.json"

# Hierarchical logger names (stable for callers)
LOGGER_COLLISION_MASK = "game.collision.mask"
LOGGER_TMX_EFFECT_PLACEMENT = "game.tmx.effect_placement"
LOGGER_TMX_LAYOUT = "game.tmx.layout"
LOGGER_ANIMATED_ENVIRONMENT = "game.animated.environment"
LOGGER_GAME_FLOW = "game.flow"
LOGGER_COMBAT = "game.combat"
LOGGER_PLAYER_ITEM = "game.player.item"
LOGGER_SPAWNER = "game.spawner"
LOGGER_INPUT = "game.input"
LOGGER_MASK_ASCII = "game.debug.mask_ascii"
LOGGER_QUADTREE = "game.quadtree"
LOGGER_EFFECT_ENVIRONMENTAL = "game.effect.environmental"
LOGGER_RTS = "game.rts"
LOGGER_GRASS = "game.grass"

# Channel keys (used in debug_logging.json) -> logger name
_CHANNEL_TO_LOGGER: Dict[str, str] = {
    "collision_mask": LOGGER_COLLISION_MASK,
    "tmx_effect_placement": LOGGER_TMX_EFFECT_PLACEMENT,
    "tmx_layout": LOGGER_TMX_LAYOUT,
    "animated_environment": LOGGER_ANIMATED_ENVIRONMENT,
    "game_flow": LOGGER_GAME_FLOW,
    "combat": LOGGER_COMBAT,
    "player_item": LOGGER_PLAYER_ITEM,
    "spawner": LOGGER_SPAWNER,
    "input": LOGGER_INPUT,
    "mask_ascii": LOGGER_MASK_ASCII,
    "quadtree": LOGGER_QUADTREE,
    "effect_environmental": LOGGER_EFFECT_ENVIRONMENTAL,
    "rts": LOGGER_RTS,
    "grass": LOGGER_GRASS,
}

_DEFAULT_CHANNELS: Dict[str, Dict[str, Any]] = {
    "collision_mask": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/mask_collision.log",
        "console": False,
    },
    "tmx_effect_placement": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/effect_placement.log",
        "console": False,
    },
    "tmx_layout": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/tmx_layout.log",
        "console": False,
    },
    "animated_environment": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/animated_environment.log",
        "console": False,
    },
    "game_flow": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/game_flow.log",
        "console": False,
    },
    "combat": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/combat.log",
        "console": False,
    },
    "player_item": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/player_item.log",
        "console": False,
    },
    "spawner": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/spawner.log",
        "console": False,
    },
    "input": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/input.log",
        "console": False,
    },
    "mask_ascii": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/mask_ascii.log",
        "console": False,
    },
    "quadtree": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/quadtree.log",
        "console": False,
    },
    "effect_environmental": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/effect_environmental.log",
        "console": False,
    },
    "rts": {
        "enabled": False,
        "level": "DEBUG",
        "file": "logs/rts.log",
        "console": True,
    },
    "grass": {
        "enabled": True,
        "level": "INFO",
        "file": "logs/grass.log",
        "console": True,
    },
}

_setup_done = False


def _parse_level(name: str) -> int:
    return getattr(logging, str(name).upper(), logging.DEBUG)


def load_debug_logging_config() -> Dict[str, Dict[str, Any]]:
    path = os.path.join(_CODE_DIR, _CONFIG_FILENAME)
    merged: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in _DEFAULT_CHANNELS.items()}
    if not os.path.isfile(path):
        return merged
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return merged
    if not isinstance(data, dict):
        return merged
    for key, base in _DEFAULT_CHANNELS.items():
        merged[key] = dict(base)
        if key in data and isinstance(data[key], dict):
            merged[key].update(data[key])
    return merged


def setup_debug_logging() -> None:
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level < logging.WARNING:
        root.setLevel(logging.WARNING)

    cfg = load_debug_logging_config()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    for channel_key, logger_name in _CHANNEL_TO_LOGGER.items():
        channel = cfg.get(channel_key, _DEFAULT_CHANNELS[channel_key])
        log = logging.getLogger(logger_name)
        log.handlers.clear()
        log.propagate = False

        if not channel.get("enabled"):
            log.setLevel(logging.CRITICAL + 1)
            log.addHandler(logging.NullHandler())
            continue

        level = _parse_level(channel.get("level", "DEBUG"))
        log.setLevel(level)
        added = False

        rel_file = channel.get("file")
        if rel_file:
            fp = os.path.normpath(os.path.join(_CODE_DIR, rel_file))
            parent = os.path.dirname(fp)
            if parent:
                os.makedirs(parent, exist_ok=True)
            fh = logging.FileHandler(fp, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(formatter)
            log.addHandler(fh)
            added = True

        if channel.get("console"):
            sh = logging.StreamHandler()
            sh.setLevel(level)
            sh.setFormatter(formatter)
            log.addHandler(sh)
            added = True

        if not added:
            log.addHandler(logging.NullHandler())


def get_debug_logger(channel_key: str) -> logging.Logger:
    """Return the logger for a channel key from debug_logging.json (e.g. ``\"tmx_layout\"``)."""
    name = _CHANNEL_TO_LOGGER.get(channel_key)
    if not name:
        return logging.getLogger(f"game.unknown.{channel_key}")
    return logging.getLogger(name)


def get_collision_mask_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_COLLISION_MASK)


def get_tmx_effect_placement_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_TMX_EFFECT_PLACEMENT)


def get_tmx_layout_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_TMX_LAYOUT)
