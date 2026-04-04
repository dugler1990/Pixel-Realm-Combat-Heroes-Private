import copy
import pygame
import random
import json
from Item import Item  # Assume this is your Item class
from Settings import TILESIZE
from loot_table import resolve_gold_drop, resolve_loot_table

class ItemSpawner:
    def __init__(self):
        
        self.items = []  # used only for farmed items atm.
        self.spawned_positions = {}
        

    def load_item_mapping(self, standard_objects_path):
        """Load item ID to configuration mapping from a JSON file."""
        with open(standard_objects_path, 'r') as file:
            standard_item_configs = json.load(file)
        self.item_mapping = {item['item_id']: item for item in standard_item_configs}
        

    def load_item_config(self, item_config_path):
        """Load item configurations from a JSON file."""
        with open(item_config_path, 'r') as file:
            self.item_configs = json.load(file)


    def spawn_fixed_items(self):
        fixed_items = []
        for config in self.item_configs:
            if config.get('spawn_type') == 'fixed':
                for position in config['positions']:  # Iterate over positions
                    item = self.create_item(config, position)
                    fixed_items.append(item)
        return fixed_items




    def drop_from_enemy(self, enemy):
        """Drop items from an enemy based on defined drop logic."""
        dropped_items = []
        drop_info = getattr(enemy, "item_drop_info", None)
        if not drop_info:
            return dropped_items
        position = [enemy.rect.bottomright[0], enemy.rect.bottomright[1]]
        for item_id, _qty in resolve_loot_table(drop_info):
            base = self.item_mapping.get(item_id)
            if not base:
                continue
            cfg = copy.deepcopy(base)
            dropped_items.append(self.create_item(cfg, position))
        gold_amt = resolve_gold_drop(drop_info, random)
        if gold_amt and gold_amt > 0:
            base = self.item_mapping.get("gold_coin")
            if base:
                cfg = copy.deepcopy(base)
                cfg["effect"] = {"gold": int(gold_amt)}
                dropped_items.append(self.create_item(cfg, position))
        return dropped_items


#### Not  currently in use
    def respawn_items(self):
        """Respawn items that continuously appear at certain locations."""
        for item_config in self.item_configs:
            #print(f"item config: {item_config}")
            item_key = item_config.get("item_id")
            
            if item_config.get('spawn_type') == 'respawn':
                for position in item_config.get('positions', []):  # Ensure it iterates over positions
                    if random.random() <= item_config.get('respawn_rate', 0):
                        item_instance = self.create_item(item_config, position)  # Create a new item instance for each position
                        # Handle adding the visual representation of the item_instance to the game
            if item_config.get('spawn_type') == 'farmed_item':
                
                #print(f"In respawn items of type farmed_item")
                #print(f"Item config currently : {item_config}")

                for position in item_config.get('positions',[]):
                    new_item = self.create_item(item_config,position)
                    self.items.append(new_item)
                    #print( f"self . items : {self.items}" )

    def update_spawn_positions(self, item_id, new_positions):
        """Updates the spawn positions for a given item_id, ensuring no duplicates."""
        
        #print(f"updating spawn items using :{new_positions}")
        #print(f"old items : {self.items}")
        for new_position in new_positions:
            #print(f"new_position:{new_position}")
            if item_id not in self.spawned_positions:
                #print("item not in spawned_positions currently...")
                self.spawned_positions[item_id] = set()

            #print(f"\n\nspawned positions: {self.spawned_positions}\n\n")

            if tuple(new_position) not in self.spawned_positions[item_id]:
                #print("position for this item does not previously exist")
                # This is a new position for the item
                self.spawned_positions[item_id].add(tuple(new_position))
                # Create the item as it's a new position
                item_config = self.item_mapping[item_id]  # Assuming item_mapping is {item_id: item_config}
                item = self.create_item(item_config, new_position)
                self.items.append(item)
        #print(f"new items : {self.items}")

    def spawn_from_chest(self, chest_position):
        """Spawn one or more items when a chest is opened."""
        for item_key, config in self.item_configs.items():
            if config.get('spawn_type') == 'chest':
                for _ in range(random.randint(1, config.get('max_items', 1))):
                    self.create_item(item_key, chest_position)


    def create_item(self, item_config, position):
        """Create and return an Item instance."""
        #position[0] = position[0] * TILESIZE
        #position[1] = position[1] * TILESIZE
        ############### CHANGE FOR NO SCALING IN INIT:

        #print(f"creating item : {item_config}")
        #print(f"position:{position}")

            # Extracting parameters with default values if not present in item_config
        float_offset = item_config.get('float_offset', 0)  # Default value is 0 if 'float_offset' is not in item_config
        float_speed = item_config.get('float_speed', 0.5)  # Default value is 0.5 if 'float_speed' is not in item_config
        float_direction = item_config.get('float_direction', 1)  # Default value is 1 if 'float_direction' is not in item_config
        float_amplitude = item_config.get("float_amplitude",5)
        
        
        #print(f" CReATED ITEM : {item_config}")
        
        return Item(
            item_config['image_path'],
            position,
            item_config['item_id'],
            item_config.get('effect'),
            item_config['effect_type'],
            item_type=item_config.get('item_type', ''),
            float_offset=float_offset,
            float_speed=float_speed,
            float_direction=float_direction,
            float_amplitude=float_amplitude,
            belt_allowed=item_config.get('belt_allowed', False),
        )

    def update(self):
        """Update method for respawning items and other time-based spawning logic."""
        #self.respawn_items()
        #print(f"  \n \n RETURNED ITEMS IN UPDATE : {self.items}")
        items_to_spawn = self.items
        self.items = []
        return items_to_spawn
      
    def remove_item(self, item):
        """Removes an item and marks its position as available."""
        if item in self.items:
            self.items.remove(item)
            item_pos = (item.pos[0] // TILESIZE, item.pos[1] // TILESIZE)
            item_id = getattr(item, "item_id", None)
            if item_id and item_pos in self.spawned_positions.get(item_id, set()):
                self.spawned_positions[item_id].remove(item_pos)

