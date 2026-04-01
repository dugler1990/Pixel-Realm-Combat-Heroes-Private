# resizing object images


import os
import math
from PIL import Image

pic_folder_dir = "./objects/"
pic_dirs = os.listdir(pic_folder_dir)

tile_size = 550
tiles_per_width = 5

tile_set_width = tiles_per_width * tile_size

additional_rows = 0
if len(pic_dirs) % tiles_per_width != 0:
    additional_rows = 1

tile_set_height = (math.floor(len(pic_dirs) / tiles_per_width) + additional_rows) * tile_size

# PIL size is (width, height)
tile_set = Image.new(mode="RGBA", size=(tile_set_width, tile_set_height))
counter = 0
for pic_dir in pic_dirs:
    pic = Image.open(pic_folder_dir + pic_dir).resize((tile_size, tile_size))
    row = math.floor(counter / tiles_per_width)
    col = counter % tiles_per_width
    x = col * tile_size
    y = row * tile_size
    tile_set.paste(pic, (x, y))
    counter += 1

tile_set.save("object_tileset.png")
