"""Build player ability instances from Settings."""

from __future__ import annotations

import json
import os

from abilities.dash import DashAbility
from abilities.held import HeldMagicAbility, HeldWeaponAbility
from abilities.instant import InstantEvasionAbility
from abilities.leap_slam import ChargedLeapSlamAbility
from abilities.player_controller import PlayerActionController
from Settings import DEFAULT_EVASION_LOADOUT, ability_data


def _player_selection_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "Graphics",
        "PlayerSelectionDict.json",
    )


def load_evasion_loadout(player_info_dir: str | None) -> list[str]:
    if not player_info_dir:
        return list(DEFAULT_EVASION_LOADOUT)
    path = _player_selection_path()
    if not os.path.exists(path):
        return list(DEFAULT_EVASION_LOADOUT)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    normalized = player_info_dir.rstrip("/") + "/"
    for entry in payload.get("Players", []):
        entry_dir = entry.get("player_info_dir", "")
        if entry_dir == player_info_dir or entry_dir == normalized:
            loadout = entry.get("evasion_loadout")
            if isinstance(loadout, list) and loadout:
                return list(loadout)
    return list(DEFAULT_EVASION_LOADOUT)


def build_ability(ability_id: str, config: dict):
    ability_type = config.get("type")
    if ability_type == "dash":
        return DashAbility(ability_id, config)
    if ability_type == "instant":
        return InstantEvasionAbility(ability_id, config)
    if ability_type == "charged_leap_slam":
        return ChargedLeapSlamAbility(ability_id, config)
    raise ValueError(f"unknown ability type {ability_type!r} for {ability_id!r}")


def build_evasion_abilities(loadout=None):
    order = list(loadout or DEFAULT_EVASION_LOADOUT)
    abilities = {}
    for ability_id in order:
        if ability_id not in ability_data:
            raise ValueError(f"unknown ability {ability_id!r} in evasion loadout")
        abilities[ability_id] = build_ability(ability_id, ability_data[ability_id])
    return abilities, order


def build_action_controller(
    player,
    create_attack,
    destroy_attack,
    create_magic,
    create_trap,
    attack_sound,
    evasion_loadout=None,
):
    weapon = HeldWeaponAbility(create_attack, attack_sound)
    magic = HeldMagicAbility(create_magic)
    evasion, evasion_order = build_evasion_abilities(evasion_loadout)
    return PlayerActionController(
        player=player,
        weapon_ability=weapon,
        magic_ability=magic,
        evasion_abilities=evasion,
        evasion_order=evasion_order,
        destroy_attack=destroy_attack,
    )
