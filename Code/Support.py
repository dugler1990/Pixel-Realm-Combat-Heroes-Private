from csv import reader
import os
from os import walk
import pygame
from game_logging import get_debug_logger

_mask_ascii_log = get_debug_logger("mask_ascii")

# Support for importing CSV files into Python and more stuff here

# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def import_csv_layout(path): 
    
    terrain_map = []

    with open(path) as level_map:
        layout = reader(level_map, delimiter = ",")

        for row in layout:
            terrain_map.append(list(row))
        
        return terrain_map


def print_mask(mask):
    # Get the size of the mask
    width, height = mask.get_size()

    # Iterate over each row of the mask
    for y in range(height):
        # Initialize an empty string to store the row
        row_str = ""
        # Iterate over each column of the mask
        for x in range(width):
            # Check if the pixel at (x, y) is colliding (1) or not (0)
            if mask.get_at((x, y)):
                # Append 1 if colliding
                row_str += "1"
            else:
                # Append 0 if not colliding
                row_str += "0"
        _mask_ascii_log.debug("%s", row_str)

def frames_to_masks(animation_frames):
    masks = []
    #print(animation_frames)
    for frame in animation_frames:
        # Use from_surface - it automatically creates mask from non-transparent pixels
        # This correctly handles alpha transparency, unlike from_threshold
        mask = pygame.mask.from_surface(frame)
        
        masks.append(mask)
    
    return masks


_CODE_DIR = os.path.dirname(os.path.abspath(__file__))


def _masks_base_dir():
    return os.path.normpath(os.path.join(_CODE_DIR, "..", "Graphics", "Masks"))


_ENTITY_MASK_CACHE = {}


def build_entity_masks_in_memory(animations_dict, animations_left_right_indicator):
    """Build collision masks from animation surfaces (no disk I/O)."""
    masks = {}
    if animations_left_right_indicator:
        for key, animation_set_left_right in animations_dict.items():
            masks_temp = {}
            for left_right_key, animation_set in animation_set_left_right.items():
                masks_temp[left_right_key] = frames_to_masks(animation_set)
            masks[key] = masks_temp
    else:
        for key, animation_set in animations_dict.items():
            masks[key] = {"default": frames_to_masks(animation_set)}
    return masks


def load_entity_masks_from_disk(monster_name, animations_dict, animations_left_right_indicator):
    """
    Load pre-exported mask PNGs if every expected file exists.
    Paths match legacy save layout under Graphics/Masks/{monster_name}/...
    """
    main_folder = os.path.join(_masks_base_dir(), monster_name)
    try:
        if animations_left_right_indicator:
            out = {}
            for key, animation_set_left_right in animations_dict.items():
                masks_temp = {}
                for left_right_key, animation_set in animation_set_left_right.items():
                    direction_folder = os.path.join(main_folder, left_right_key)
                    frames = []
                    for i in range(len(animation_set)):
                        image_path = os.path.join(
                            direction_folder, f"{key}_{left_right_key}_mask_{i}.png"
                        )
                        if not os.path.isfile(image_path):
                            return None
                        surf = pygame.image.load(image_path).convert_alpha()
                        frames.append(pygame.mask.from_surface(surf))
                    masks_temp[left_right_key] = frames
                out[key] = masks_temp
            return out
        out = {}
        for key, animation_set in animations_dict.items():
            direction_folder = main_folder
            frames = []
            for i in range(len(animation_set)):
                image_path = os.path.join(direction_folder, f"{key}_mask_{i}.png")
                if not os.path.isfile(image_path):
                    return None
                surf = pygame.image.load(image_path).convert_alpha()
                frames.append(pygame.mask.from_surface(surf))
            out[key] = {"default": frames}
        return out
    except (pygame.error, OSError):
        return None


def _export_entity_masks_to_disk(monster_name, masks, animations_left_right_indicator):
    """Write mask PNGs for tooling (dev-only when EXPORT_ENTITY_MASKS_TO_DISK is True)."""
    main_folder = os.path.join(_masks_base_dir(), monster_name)
    os.makedirs(main_folder, exist_ok=True)
    if animations_left_right_indicator:
        for key, animation_set_left_right in masks.items():
            for left_right_key, mask_frames in animation_set_left_right.items():
                direction_folder = os.path.join(main_folder, left_right_key)
                os.makedirs(direction_folder, exist_ok=True)
                for i, mask in enumerate(mask_frames):
                    if mask is not None:
                        image_path = os.path.join(
                            direction_folder, f"{key}_{left_right_key}_mask_{i}.png"
                        )
                        pygame.image.save(mask.to_surface(), image_path)
    else:
        for key, bucket in masks.items():
            mask_frames = bucket.get("default", [])
            for i, mask in enumerate(mask_frames):
                if mask is not None:
                    image_path = os.path.join(main_folder, f"{key}_mask_{i}.png")
                    pygame.image.save(mask.to_surface(), image_path)


def get_or_build_entity_masks(
    monster_name,
    animations_dict,
    animations_left_right_indicator,
    *,
    skip_disk=False,
):
    """
    Return nested dict of pygame masks; prefer disk load, then cache, else build in memory.
    skip_disk=True for per-instance scaled sprites (e.g. tribey_snake).
    """
    from Settings import EXPORT_ENTITY_MASKS_TO_DISK

    if skip_disk:
        masks = build_entity_masks_in_memory(animations_dict, animations_left_right_indicator)
        if EXPORT_ENTITY_MASKS_TO_DISK:
            _export_entity_masks_to_disk(monster_name, masks, animations_left_right_indicator)
        return masks

    cache_key = (monster_name, animations_left_right_indicator)
    if cache_key in _ENTITY_MASK_CACHE:
        return _ENTITY_MASK_CACHE[cache_key]

    loaded = load_entity_masks_from_disk(monster_name, animations_dict, animations_left_right_indicator)
    if loaded is not None:
        _ENTITY_MASK_CACHE[cache_key] = loaded
        return loaded

    masks = build_entity_masks_in_memory(animations_dict, animations_left_right_indicator)
    if EXPORT_ENTITY_MASKS_TO_DISK:
        _export_entity_masks_to_disk(monster_name, masks, animations_left_right_indicator)
    _ENTITY_MASK_CACHE[cache_key] = masks
    return masks

def import_folder(path, scale=None):
    surface_list = []
    for _, __, img_files in walk(path):
        for image in img_files:
            full_path = os.path.join(path, image)
            image_surf = pygame.image.load(full_path).convert_alpha()
            if scale:
                image_surf = pygame.transform.scale(image_surf, scale)
                #image_surf.set_alpha(200)
            surface_list.append(image_surf)
    return surface_list


def import_folder_old(path):
    
    surface_list = []
    
    for _, __, img_files in walk(path):
        for image in img_files:
            full_path = path + "/" + image
            image_surf = pygame.image.load(full_path).convert_alpha()
            surface_list.append(image_surf)
    return surface_list