from csv import reader
import os
from os import walk
import pygame

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
        # Print the row string
        print(row_str)

def frames_to_masks(animation_frames):
    masks = []
    #print(animation_frames)
    for frame in animation_frames:
        # Use from_surface - it automatically creates mask from non-transparent pixels
        # This correctly handles alpha transparency, unlike from_threshold
        mask = pygame.mask.from_surface(frame)
        
        masks.append(mask)
    
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