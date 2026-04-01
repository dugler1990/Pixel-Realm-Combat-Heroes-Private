# tmx import test

import pytmx

map1 = pytmx.TiledMap("map1.tmx")




# with pygame
import pygame
from pytmx.util_pygame import load_pygame

# Initialize pygame
pygame.init()

# Set up a basic display window (adjust size if needed)
screen = pygame.display.set_mode((1280, 1280))  # Small window for testing
pygame.display.set_caption("Tile Test")


tmxdata = load_pygame("../levels/tmx/map.tmx")

surface = tmxdata.get_tile_image(2,2,0)
pygame.image.save(surface, "tile_image.png")



# Main loop to display the tile
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    screen.fill((0, 0, 0))  # Clear screen with black
    if surface:
        screen.blit(surface, (32, 32))  # Draw the tile at (32, 32)
    
    pygame.display.flip()  # Update display
