

class YSortCameraGroup_old(pygame.sprite.Group):
    def __init__(self,ground_sprites): # Ground sprites in this version because it defines the ground with tiles ( ground_sprites ) 
        super().__init__()
        self.display_surface = pygame.display.get_surface()
        self.half_width = self.display_surface.get_size()[0] // 2
        self.half_height = self.display_surface.get_size()[1] // 2
        self.offset = pygame.math.Vector2()
        self.ground_sprites = ground_sprites

#        self.floor_surf = pygame.image.load("../Graphics/Tilemap/Ground.png").convert()
#        self.floor_rect = self.floor_surf.get_rect(topleft = (0, 0))
    ###@profile #decorator to be used for profiling with line_profile, must run Main like this : kernprof -l -v Main2.py
    def custom_draw_withearthquakeeffect(self, player):
        
        self.offset.x = player.rect.centerx - self.half_width
        self.offset.y = player.rect.centery - self.half_height

        # Draw ground tiles with slight offset and blending
        for sprite in sorted(self.ground_sprites, key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            # Slightly offset tile position
            offset_pos += pygame.math.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
            # Draw tile
            self.display_surface.blit(sprite.image, offset_pos)
            # Draw semi-transparent overlay on tile edges for blending
            overlay = pygame.Surface((sprite.rect.width, sprite.rect.height), pygame.SRCALPHA)
            pygame.draw.rect(overlay, (255, 255, 255, 128), overlay.get_rect(), 1)
            self.display_surface.blit(overlay, offset_pos)

        # Draw other sprites
        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)



    def custom_draw(self, player):
        self.offset.x = player.rect.centerx - self.half_width
        self.offset.y = player.rect.centery - self.half_height

  # Draw ground tiles first
        for sprite in sorted(self.ground_sprites, key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)

        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)



    def update(self,dt = None, *args, **kwargs):
        # Update all sprites, passing the player as an argument to those that need it
        for sprite in self.sprites():

            # JUST A POTENTIAL EFFICIENCY IMPROVEMENT TO ONLY PASS PLAYER TO NECESSARY UPDATES ? NO, ITS JUST IF I MAKE THE ENEMY_UPDATE AND REGULAR SPRITE.update method the  same...
            # Pretty sure it was jst a bad idea, but there it is.

            #if hasattr(sprite, 'update_with_player') and sprite.update_with_players:
                #sprite.update(self, player)  # Custom method for sprites needing the player
            #else:
            if isinstance(sprite, Eskimo):
                #print(f"SPRITE BEFORE UPDATE : {sprite}")
                sprite.update(dt)
                #print(f"SPRITE AFTER UPDATE : {sprite}")
            else:
                sprite.update(*args, **kwargs)
