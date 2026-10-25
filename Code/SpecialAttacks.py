import random
from pygame import Vector2
import pygame
from functools import partial
import math
from Settings import TILESIZE
from game_logging import get_debug_logger
from abilities.dash import DashAbility
from abilities.protocol import CombatAbilityContext

_combat_log = get_debug_logger("combat")




def in_range_of_player(enemy, player, radius):
    distance = Vector2(enemy.rect.center).distance_to(Vector2(player.rect.center))
    return distance <= radius


def health_below_threshold(enemy, player, threshold):
    return enemy.health <= threshold

def create_trigger_condition(trigger_config):
    name = trigger_config['name']
    parameters = trigger_config.get('parameters', {})

    if name == 'in_range_of_player':
        radius = parameters.get('radius', 100)
        return partial(in_range_of_player, radius=radius)
    elif name == 'health_below_threshold':
        threshold = parameters.get('threshold', 50)
        return partial(health_below_threshold, threshold=threshold)
    else:
        raise ValueError(f"Unknown trigger condition name: {name}")





def create_special_attack(attack_config):
    name = attack_config['name']
    cooldown = attack_config['cooldown']
    cooldown_variability = attack_config['cooldown_variability']
    trigger_conditions = attack_config.get('trigger_conditions', [])  # Now a list of dicts
    chance = attack_config.get('chance', 1) 

    if name == 'Teleport':
        #print("detected Teleport")
        max_distance = attack_config['max_distance']
        return TeleportAttack(cooldown, cooldown_variability, trigger_conditions, max_distance, chance)
    elif name == 'MultiShotIceball':
        num_shots = attack_config['num_shots']
        projectile_type = attack_config['projectile_type']
        return MultiShotIceball(cooldown, cooldown_variability, trigger_conditions, num_shots, projectile_type,chance)
    elif name == 'SummonIceGhosts':
        spawn_radius = attack_config['spawn_radius']
        cast_time = attack_config['cast_time']
        damage_threshold = attack_config['damage_threshold']
        return SummonIceGhosts(cooldown,
                               cooldown_variability,
                               trigger_conditions,
                               spawn_radius,
                               cast_time,
                               damage_threshold,
                               chance)
    elif name == 'Dash':
        return DashAttack(cooldown, cooldown_variability, trigger_conditions, attack_config, chance)
    elif name == 'MeteorShower':
        return MeteorShower(cooldown, cooldown_variability, trigger_conditions, attack_config, chance)
    else:
        raise ValueError(f"Unknown special attack name: {name}")







class SpecialAttack:
    def __init__(self, name, cooldown, cooldown_variability, trigger_conditions):
        self.name = name
        self.base_cooldown = cooldown
        self.cooldown_variability = cooldown_variability
        self.trigger_conditions = [create_trigger_condition(cond) for cond in trigger_conditions]
        #print(f"trigger conditions created:{self.trigger_conditions}")
        self.last_used_time = 0

    def execute(self, enemy, player, context):
        raise NotImplementedError

    def is_ready(self, current_time):
        return current_time - self.last_used_time >= self.base_cooldown + random.uniform(-self.cooldown_variability, self.cooldown_variability)


    def can_trigger(self, enemy, player):
        return all(cond(enemy, player) for cond in self.trigger_conditions)

def dash_direction_toward_player(enemy, player):
    if player.rect.centerx >= enemy.rect.centerx:
        return "right"
    return "left"


class DashAttack(SpecialAttack):
    def __init__(self, cooldown, cooldown_variability, trigger_conditions, attack_config, chance):
        super().__init__("Dash", cooldown, cooldown_variability, trigger_conditions)
        self.chance = chance
        dash_config = {
            "cost": attack_config.get("cost", 0),
            "speed_mult": attack_config.get("speed_mult", 2),
            "duration_ms": attack_config.get("duration_ms", 350),
            "collision_mode": attack_config.get("collision_mode", "pass_through"),
            "stop_on_wall": attack_config.get("stop_on_wall", False),
            "damage": attack_config.get("damage"),
            "attack_type": attack_config.get("attack_type", "melee"),
            "hit_once_per_target": attack_config.get("hit_once_per_target", True),
            "presentation": attack_config.get(
                "presentation",
                {"status_template": "move", "end_status": "idle"},
            ),
        }
        self.dash_ability = DashAbility("dash", dash_config)

    def execute(self, enemy, player, context):
        if random.random() >= self.chance:
            return
        direction = dash_direction_toward_player(enemy, player)
        ability_context = CombatAbilityContext(combat_context=context)
        if self.dash_ability.try_start(enemy, ability_context, direction=direction):
            self.last_used_time = pygame.time.get_ticks()


class TeleportAttack(SpecialAttack):
    def __init__(self, cooldown, cooldown_variability, trigger_condition, max_distance, chance):
        super().__init__('Teleport', cooldown, cooldown_variability, trigger_condition)
        self.max_distance = max_distance
        self.chance = chance
        
    def execute(self, enemy, player, context):
        #print(f"executing teleport !!")
        if random.random() < self.chance:# TODO: make this a function of the Special attack they all have it
            direction_vector = Vector2(enemy.rect.center) - Vector2(player.rect.center)
            if direction_vector.length() > 0:
                direction_vector.normalize_ip()
                teleport_position = Vector2(player.rect.center) + direction_vector * self.max_distance * random.gauss(0.90,0.03)
                enemy.rect.center = teleport_position
                enemy.hitbox.center = teleport_position
                enemy.status = 'Teleport'
            self.last_used_time = pygame.time.get_ticks()

class MultiShotIceball(SpecialAttack):
    def __init__(self,
                 cooldown,
                 cooldown_variability,
                 trigger_condition,
                 num_shots,
                 projectile_type,
                 chance):
        super().__init__('MultiShotIceball', cooldown, cooldown_variability, trigger_condition)
        self.num_shots = num_shots
        self.projectile_type = projectile_type
        self.chance = chance

    def execute(self, enemy, player, context):
        if random.random() < self.chance:
            for _ in range(self.num_shots):
                random_direction = Vector2(random.uniform(-1, 1), random.uniform(-1, 1)).normalize()
                
                
                context["fire_projectile"]( enemy_pos = enemy.rect.center,
                                            target_pos = enemy.rect.center + random_direction * 50,
                                            projectile_type = self.projectile_type,
                                            groups = enemy.groups,
                                            owner=enemy,
                                            source_team=getattr(enemy, "team_id", None),
                                            amount=None)
            enemy.status = 'MultiShotIceball'
            self.last_used_time = pygame.time.get_ticks()
            
            
class SummonIceGhosts(SpecialAttack):
    def __init__(self, cooldown, cooldown_variability, trigger_condition, spawn_radius, cast_time, damage_threshold, chance):
        super().__init__('SummonIceGhosts', cooldown, cooldown_variability, trigger_condition)
        self.spawn_radius = spawn_radius
        self.cast_time = cast_time
        self.damage_threshold = damage_threshold
        self.is_casting = False
        self.cast_start_time = None
        self.starting_health = 0
        self.chance = chance

    def execute(self, enemy, player, context):
        if random.random() < self.chance:
            self.is_casting = True
            self.cast_start_time = pygame.time.get_ticks()
            self.starting_health = enemy.health  # Capture the health at the start of casting
            
            enemy.status = 'Summoning'

    def update(self, enemy, player, context):
        if not self.is_casting:
            return

        current_time = pygame.time.get_ticks()
        _combat_log.debug(
            "udpate : current:%s  start :%s cast_time = %s",
            current_time,
            self.cast_start_time,
            self.cast_time,
        )
        if current_time - self.cast_start_time >= self.cast_time:
            damage_taken_during_cast = self.starting_health - enemy.health
            _combat_log.debug(
                "damage taken : %s, thresh: %s",
                damage_taken_during_cast,
                self.damage_threshold,
            )
            if damage_taken_during_cast < self.damage_threshold:
                num_ghosts_to_spawn = 3  # You can adjust this number as needed
                for _ in range(num_ghosts_to_spawn):
                    
                    spawn_pos = self.generate_random_position(enemy.rect.center, self.spawn_radius)
                    _combat_log.debug("spawn pos  : %s", spawn_pos)
                    context["spawn_enemy"](config = {
                                            'type': 'ice_ghost',
                                            'spawn_team_id': getattr(enemy, "team_id", None),
                                        },
                                        pos = spawn_pos)
                    _combat_log.debug("supposidly spawned ghost")
            self.is_casting = False
            enemy.status = 'idle'
            self.last_used_time = current_time
        else:
            # Check if the damage threshold is exceeded during casting
            damage_taken_during_cast = self.starting_health - enemy.health
            if damage_taken_during_cast >= self.damage_threshold:
                self.is_casting = False
                enemy.status = 'idle'

    def generate_random_position(self, center, radius):
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(0, radius)/TILESIZE
        offset_x = math.cos(angle) * distance
        offset_y = math.sin(angle) * distance
        return (center[0]/TILESIZE + offset_x, center[1]/TILESIZE + offset_y)


class MeteorShower(SpecialAttack):
    """Spend mana, play cast1_swift once, keep fighting while meteors rain."""

    # Shower ticks in the background; does not lock melee/move (cast is a oneshot mesh).
    lock_actions = False

    def __init__(self, cooldown, cooldown_variability, trigger_conditions, attack_config, chance):
        super().__init__("MeteorShower", cooldown, cooldown_variability, trigger_conditions)
        self.chance = chance
        self.duration_ms = int(attack_config.get("duration_ms", 20000))
        self.spawn_interval_ms = int(attack_config.get("spawn_interval_ms", 450))
        self.scatter_radius = float(attack_config.get("scatter_radius", 420))
        self.scale_min = float(attack_config.get("scale_min", 0.35))
        self.scale_max = float(attack_config.get("scale_max", 1.6))
        self.burst_damage = int(attack_config.get("burst_damage", 75))
        self.dot_damage = int(attack_config.get("dot_damage", 8))
        self.dot_interval_ms = int(attack_config.get("dot_interval_ms", 500))
        self.linger_ms = int(attack_config.get("linger_ms", 3000))
        self.impact_radius = float(attack_config.get("impact_radius", 90))
        self.knockback = float(attack_config.get("knockback", 252))
        self.knockback_follow_through = float(attack_config.get("knockback_follow_through", 0.55))
        # Uniform size dist: shake when scale >= mean + 1σ.
        span = max(1e-6, self.scale_max - self.scale_min)
        mean = 0.5 * (self.scale_min + self.scale_max)
        std = span / math.sqrt(12.0)
        self.shake_scale_threshold = float(
            attack_config.get("shake_scale_threshold", mean + std)
        )
        self.mana_cost = float(attack_config.get("mana_cost", attack_config.get("energy_cost", 80)))
        self.cast_action = str(attack_config.get("cast_action", "cast1_swift"))
        self.is_casting = False
        self.cast_start_time = None
        self.last_spawn_time = None

    def execute(self, enemy, player, context):
        if random.random() >= self.chance:
            return
        energy = float(getattr(enemy, "energy", 0) or 0)
        if energy < self.mana_cost:
            return
        enemy.energy = energy - self.mana_cost
        self.is_casting = True
        now = pygame.time.get_ticks()
        self.cast_start_time = now
        self.last_spawn_time = now - self.spawn_interval_ms  # spawn first immediately
        # One-shot cast pose; AI resumes immediately while shower updates in background.
        if hasattr(enemy, "start_mesh_oneshot"):
            enemy.start_mesh_oneshot(self.cast_action)

    def update(self, enemy, player, context):
        if not self.is_casting:
            return
        now = pygame.time.get_ticks()
        if now - self.cast_start_time >= self.duration_ms:
            self.is_casting = False
            self.last_used_time = now
            return

        if now - self.last_spawn_time < self.spawn_interval_ms:
            return
        self.last_spawn_time = now

        spawn_fn = context.get("spawn_meteor")
        if spawn_fn is None:
            return

        anchor = getattr(player, "rect", None)
        center = anchor.center if anchor is not None else enemy.rect.center
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0, self.scatter_radius)
        pos = (center[0] + math.cos(angle) * dist, center[1] + math.sin(angle) * dist)
        scale = random.uniform(self.scale_min, self.scale_max)
        spawn_fn(
            pos,
            scale=scale,
            owner=enemy,
            source_team=getattr(enemy, "team_id", "enemy"),
            burst_damage=self.burst_damage,
            dot_damage=self.dot_damage,
            dot_interval_ms=self.dot_interval_ms,
            linger_ms=self.linger_ms,
            impact_radius=self.impact_radius,
            knockback=self.knockback,
            knockback_follow_through=self.knockback_follow_through,
            shake_scale_threshold=self.shake_scale_threshold,
        )
