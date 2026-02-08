from cmath import rect
import pygame
from math import sin
import os
import math
from hashRect import HashableRect
from Support import print_mask
from Effect import EFFECT_REGISTRY
# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))
MAX_DISPLACEMENT = 5.5

# Movement constants
BASE_ACCELERATION = 0.4  # Base acceleration rate (higher = faster acceleration, lower = more control)
DEFAULT_FRICTION = 0.5  # Default friction multiplier for normal movement (0.95 = 5% velocity loss per frame, minimal inertia)
MAX_VELOCITY_MULTIPLIER = 1  # Max velocity can be this much higher than base speed

class Entity(pygame.sprite.Sprite):
    # Class-level variable to keep track of IDs
    id_counter = 0
    def __init__(self, groups, layout_callback_update_quad_tree = None):
        super().__init__(groups)
        Entity.id_counter += 1
        self.id = Entity.id_counter
        self.frame_index = 0
        self.animation_speed = 0.25
        self.direction = pygame.math.Vector2()
        self.velocity = pygame.math.Vector2(0, 0)  # Current velocity for movement
        self.weight = 1.0  # Weight affects acceleration (higher weight = slower acceleration)
        self.max_collision_distance_squared = 10000
        self.max_collision_distance = 10
        self.mask = None
        # Flag to track whether move method has been called before
        self.move_not_called_before = True
        # Active effects tracking: {effect_area_id: effect_instance}
        self.active_effects = {}
        if layout_callback_update_quad_tree :
            self.layout_callback_update_quad_tree = layout_callback_update_quad_tree
        else:
            def empty_func_is_not_nicey(*args, alive = True, remove_existing = True):pass
            self.layout_callback_update_quad_tree  =  empty_func_is_not_nicey
    #@profile
    def move(self, speed, QuadTree,entity_quad_tree, update_quad_tree = True):
        
        
        
        #print(f'speed as stated in move method: {speed}')
        #print(f"Quadtree in move method : {entity_quad_tree.manager.item_mapping}")
        #print( f"self.move_not_called_before : {self.move_not_called_before}" )
        remove_existing = not self.move_not_called_before
        #print(f"remove existing : {remove_existing}")
        if update_quad_tree:
            if hasattr(self, 'sprite_type'):
                sprite_type = self.sprite_type
            else:
                sprite_type = None
                
            if hasattr(self, 'mask'):
                mask = self.mask
            else:
                mask = None
        
        
        
            self.layout_callback_update_quad_tree(HashableRect(self.rect,
                                                               self.id,
                                                               self.direction,
                                                               sprite_type,
                                                               mask),
                                                  alive = True,
                                                  remove_existing = remove_existing)
            # Update flag after the first call
            self.move_not_called_before = False
        # if hasattr(self, "type" ): 
        #     if self.type == "player":
        #         print(f"hitbo pre : {self.hitbox}")
        #         print(f"self.animation spee : {self.animation_speed}")
     
        # Normalize direction if not zero
        input_direction = pygame.math.Vector2(0, 0)
        if self.direction.magnitude() != 0:
            input_direction = self.direction.normalize()
        
        # Calculate effective acceleration and friction multipliers from active effects
        # Get MIN acceleration (most restrictive) and max friction (higher friction_multiplier = more slippery)
        acceleration_multiplier = 1.0  # Start with normal (1.0)
        friction_multiplier = DEFAULT_FRICTION  # Start with default normal friction
        
        for effect in self.active_effects.values():
            acc_mult = effect.get_acceleration_multiplier()
            fric_mult = effect.get_friction_multiplier()
            if acc_mult < acceleration_multiplier:  # Use MINIMUM (most restrictive) for slippery surfaces
                acceleration_multiplier = acc_mult
            if fric_mult > friction_multiplier:  # Higher friction_multiplier = more slippery (less friction loss)
                friction_multiplier = fric_mult
        
        # Apply traction physics: reduce acceleration more when turning than when moving straight
        # This creates realistic drifting - you maintain forward momentum but can't turn quickly
        effective_acceleration_multiplier = acceleration_multiplier
        
        if input_direction.magnitude() > 0 and self.velocity.magnitude() > 0.1:
            # Calculate angle between velocity and input direction using dot product
            # Normalize both vectors for accurate angle calculation
            velocity_normalized = self.velocity.normalize()
            input_normalized = input_direction.normalize()
            
            # Dot product gives cos(angle), so angle = arccos(dot)
            # When vectors are parallel (moving straight): dot ≈ 1, angle ≈ 0°
            # When vectors are perpendicular (turning): dot ≈ 0, angle ≈ 90°
            dot_product = velocity_normalized.dot(input_normalized)
            # Clamp dot product to [-1, 1] to avoid math domain errors
            dot_product = max(-1.0, min(1.0, dot_product))
            
            # Calculate angle in radians (0° = parallel, 90° = perpendicular)
            angle_radians = math.acos(dot_product)
            
            # Apply traction multiplier: reduce acceleration more for perpendicular components (turning)
            # Formula: traction_multiplier = 1.0 - (1.0 - acceleration_multiplier) * sin(angle)
            # When moving straight (angle ≈ 0°): sin(0) ≈ 0, minimal reduction
            # When turning 90°: sin(90°) = 1, full reduction from slippery effect
            sin_angle = math.sin(angle_radians)
            traction_multiplier = 1.0 - (1.0 - acceleration_multiplier) * sin_angle
            effective_acceleration_multiplier = traction_multiplier
        
        # Apply input acceleration
        if input_direction.magnitude() > 0:
            # Accelerate towards input direction
            # Weight affects acceleration: heavier entities accelerate slower
            weight_factor = 1.0 / self.weight  # Inverse relationship
            acceleration = BASE_ACCELERATION * effective_acceleration_multiplier * weight_factor
            target_velocity = input_direction * speed * MAX_VELOCITY_MULTIPLIER
            # Manually interpolate velocity towards target (acceleration)
            velocity_delta = (target_velocity - self.velocity) * acceleration
            self.velocity += velocity_delta
        else:
            # Apply friction when no input
            # friction_multiplier directly multiplies velocity (lower = more slippery)
            # Normal movement: DEFAULT_FRICTION (0.95 = 5% loss per frame)
            # Slippery effects: lower multiplier (e.g., 0.98 = 2% loss per frame, more slippery)
            self.velocity *= friction_multiplier
            # Stop very small velocities to prevent jitter
            if self.velocity.magnitude() < 0.1:
                self.velocity = pygame.math.Vector2(0, 0)
        
        # Apply velocity to position
        self.hitbox.x += self.velocity.x
        self.hitbox.y += self.velocity.y
        
        
        # if hasattr(self, "type" ): 
        #     if self.type == "player":
        #         print(f"hitbo pre : {self.hitbox}")
     
        
        #self.collision("Vertical",QuadTree=QuadTree)
        self.rect.center = self.hitbox.center
        #print(f"rec center post move  : {self.rect.center}")
        
        self.collision(  
                        QuadTree=QuadTree ,
                        entity_quad_tree = entity_quad_tree,
                        speed = speed
                        )
        


    #@profile
    def collision(self, QuadTree, entity_quad_tree, speed = 0):# Speed is just to adjust displacement when colliding with objects so you dont go through
                                                                  # Maybe i should do the same with entity collisions.
        
        """
        Issues with this function : i have a bunch of conditions and each one actually
        moved the player, as opposed to keeping track of a displacement, 
        this is because if there is a collision and then we notice a obstacle collision of the deflection of that 
        collision, we do not make the movement change in terms of displacement, we use the obstacle 
        boundry. We could surely fix this but this is just so that you dont get too lost.
        
        explanation of function 
        
        check collisions with any obstacles, if that happens, thats all that happens, 
        
        if there are no imediate obstacle collisions, check entity collisions, 
        
            if entity is stationary , consider the collision like into a wall
                 TODO, they should take some impact depending on size
                 
            if the entity is moving, we do some basic calcs about increasing rebound based on relative velocity
            but we just rebound on the normal of the collision , rbound is larger if the entity is bigger
            
            if rebounding from an entity would result in you colliding with an object, you appear at theb oundry of the object
            im still worrid you could get hit simultansouly by a bunch of entites and go through an obstacle
            lets see.
            
            seems to work ok , being in a corner ( secondary collision with vertical and horizontal wall can go wrong.)
            
            would be cool if there was some dampening some how, like, at the moment if you get stuck in a corner
            you bound around like crazy, would be nice if... you needed speed for that, i dno.
        
        
            """
            
            
        # Define displacement for collision resolution with obstacles
        displacement_obstacles = 1  
        MAX_DISPLACEMENT = speed
        
        total_displacement_x = 0
        total_displacement_y = 0
        max_penetration_depth = 0
        
        # Define base displacement for entity collisions
        base_displacement_entities = 1.1  # Adjust this value as needed
        exponent = 4 # Adjust this exponent for the desired relationship
        
        
        ## Handle effect collisions.
        
        
        # Check for nearby obstacles using the QuadTree
        nearby_obstacles = QuadTree.hit(HashableRect(self.rect, self.id))
        nearby_entities = entity_quad_tree.hit(HashableRect(self.rect, self.id))
        
        # if hasattr(self,'type'):
        #     if self.type == "player" :
        #         print_mask(self.mask)
        
        
        # if hasattr(self, 'monster_name'):
        #     if self.monster_name == 'raccoon':
            
        #         print(self.monster_name)
                #print(f"nearby obstacles : {nearby_obstacles}")
                
                #print(f"nearby entities : {nearby_entities}")
        
        
        # Iterate over nearby obstacles (walls)
        for obstacle in nearby_obstacles:
            do_collision = True
            
            # DEBUG: Log mask status to file
            log_path = os.path.join(os.path.dirname(__file__), "mask_debug.log")
            with open(log_path, "a") as f:
                f.write(f"Obstacle collision - self.mask: {self.mask is not None}, obstacle.mask: {getattr(obstacle, 'mask', None) is not None}\n")
                if self.mask:
                    f.write(f"  self.mask size: {self.mask.get_size() if self.mask else 'None'}\n")
                if hasattr(obstacle, 'mask') and obstacle.mask:
                    f.write(f"  obstacle.mask size: {obstacle.mask.get_size() if obstacle.mask else 'None'}\n")
            
            if self.mask and obstacle.mask:
                # Calculate the difference between the center positions of the two entities
                dx = obstacle.rect.x - self.rect.x
                dy = obstacle.rect.y - self.rect.y
    
                # DEBUG: Log detailed rect and mask info
                with open(log_path, "a") as f:
                    entity_mask_size = self.mask.get_size()
                    entity_rect_size = (self.rect.width, self.rect.height)
                    obstacle_mask_size = obstacle.mask.get_size()
                    obstacle_rect_size = (obstacle.rect.width, obstacle.rect.height)
                    f.write(f"  Entity rect: {self.rect} (x={self.rect.x}, y={self.rect.y}, w={self.rect.width}, h={self.rect.height})\n")
                    f.write(f"  Obstacle rect: {obstacle.rect} (x={obstacle.rect.x}, y={obstacle.rect.y}, w={obstacle.rect.width}, h={obstacle.rect.height})\n")
                    f.write(f"  Entity mask size: {entity_mask_size}, Entity rect size: {entity_rect_size}\n")
                    f.write(f"  Obstacle mask size: {obstacle_mask_size}, Obstacle rect size: {obstacle_rect_size}\n")
                    if entity_mask_size != entity_rect_size:
                        f.write(f"  WARNING: Entity mask size {entity_mask_size} != rect size {entity_rect_size}\n")
                    if obstacle_mask_size != obstacle_rect_size:
                        f.write(f"  WARNING: Obstacle mask size {obstacle_mask_size} != rect size {obstacle_rect_size}\n")
                    f.write(f"  Offset (dx, dy): ({dx}, {dy})\n")
    
                overlap = self.mask.overlap_area(obstacle.mask, (dx, dy))
                
                # DEBUG: Log overlap result
                with open(log_path, "a") as f:
                    f.write(f"  Mask overlap check - dx: {dx}, dy: {dy}, overlap: {overlap}\n")
                
                if overlap == 0:
                    do_collision = False
                    # DEBUG: Log when mask filter works
                    with open(log_path, "a") as f:
                        f.write(f"  Mask filter worked - no collision (overlap == 0)\n")
                else:
                    # DEBUG: Log when collision is confirmed
                    with open(log_path, "a") as f:
                        f.write(f"  Mask collision confirmed - overlap: {overlap} pixels\n")
            else:
                # DEBUG: Log why mask check was skipped
                with open(log_path, "a") as f:
                    f.write(f"  Skipping mask check - using rect collision\n")
    
            if do_collision:
                # Calculate the angle of collision relative to the entity's movement direction
                collision_normal = math.atan2(obstacle.rect.centery - self.rect.centery, obstacle.rect.centerx - self.rect.centerx)
                rebound_angle = collision_normal + math.pi
    
                # Calculate the penetration depth
                penetration_x = max(0, self.rect.right - obstacle.rect.left, obstacle.rect.right - self.rect.left)
                penetration_y = max(0, self.rect.bottom - obstacle.rect.top, obstacle.rect.bottom - self.rect.top)
                penetration_depth = math.sqrt(penetration_x**2 + penetration_y**2)**1.5
    
                # Update total displacement vector
                total_displacement_x += math.cos(rebound_angle)
                total_displacement_y += math.sin(rebound_angle)
    
                # Update the maximum penetration depth
                max_penetration_depth = max(max_penetration_depth, penetration_depth)
    
        # Normalize the total displacement direction
        displacement_magnitude = math.sqrt(total_displacement_x**2 + total_displacement_y**2)
        if displacement_magnitude > 0:
            total_displacement_x /= displacement_magnitude
            total_displacement_y /= displacement_magnitude
    
        # Scale the displacement based on the maximum penetration depth
        
        # print(displacement_obstacles)
        # print(max_penetration_depth)
        # print(MAX_DISPLACEMENT)
        
        scaled_displacement = min(displacement_obstacles + max_penetration_depth, MAX_DISPLACEMENT)
        # print("scaled_displacement")
        # print(scaled_displacement)
        # Apply the displacement to the entity's position
        self.hitbox.left += scaled_displacement * total_displacement_x
        self.hitbox.top += scaled_displacement * total_displacement_y
        # if hasattr(self,'type'):
        #     if self.type == "player" :
                
                
        #         print(f"displacement x : {scaled_displacement * math.cos(total_displacement_x)}")
        #         print(f"displacement y : {scaled_displacement * math.sin(total_displacement_y)}")
                

        # #print(dir(entity))
        # if hasattr(self, 'monster_name'):
        #     print("hey")
        #     print(self.monster_name)
        #     if self.monster_name == 'raccoon':
        #         print(f"nearby_obstacles :{nearby_obstacles} ")
        
        # If not colliding with a wall, handle entity collisions
        if not nearby_obstacles:
            for entity in nearby_entities:
                # Check if the other entity is stationary
                
                
                # #print(dir(entity))
                # if hasattr(self, 'monster_name'):
                #     print("hey")
                #     print(self.monster_name)
                #     if self.monster_name == 'raccoon':
                #         print(f"entity  direction :{entity.direction} ")
                        
                #         print(f"entity direction :{entity.direction.magnitude()} ")
                        
                #         print("self:")
                #         print_mask(self.mask)
                #         print("entity")
                #         print_mask(entity.mask)
                
                """
                so here , if the entity doesnt have a mask , because its nerby we collide, if it doesnt have a 
                mask, we just collide it anyway
                
                at the moment all enemies have masks and player, no neutrals or objects.
                
                what it seems like to me though, is that the images with the alpha were already acting like masks
                
                regardless, it will be good to be able to play with how the mask collisions happen.
                
                """
                
                do_colision = True
                if  self.mask and entity.mask:
                    #print("self:")
                    #print_mask(self.mask)
                    #print("entity")
                    #print_mask(entity.mask)
                    # Calculate the difference between the center positions of the two entities
                    dx = entity.rect.x - self.rect.x
                    dy = entity.rect.y - self.rect.y

                    overlap = self.mask.overlap_area( entity.mask, (dx,dy) )
                    # print('overlap')
                    # print(overlap)
                    if overlap == 0 :
                        
                        #print("both masks exist")
                        #print(overlap)
                        do_colision = False
                    
                # if hasattr(entity, 'sprite_type'):
                #     if entity.sprite_type == 'magic':
                #         print(f"magic direction :{entity.direction} ") 
                
                
                # if hasattr(entity, 'sprite_type'):
                #     if entity.sprite_type == 'player':
                #         print(f"player direction :{entity.direction} ") 
                
                    
                if do_colision and entity.direction:
                    
                    
                    if entity.direction.magnitude() == 0  :
                        # second or is just because of an error, shouldnt exist, player can have None? particle maybe ?
                    
                        
                        angle_radians = math.atan2(self.direction.y, self.direction.x)
                        angle_degrees = math.degrees(angle_radians)
                        
                        
                   
                        
                        # Calculate the angle between the entity's direction and the collision normal
                        collision_normal = math.atan2(entity.rect.centery - self.rect.centery, entity.rect.centerx - self.rect.centerx)
                        
                        
                        # if hasattr(entity, 'sprite_type'):
                        #     if entity.sprite_type== 'Eskimo':
                        #         print(f"stationary eskimo collision normal :{collision_normal} ")
                        
                        # Calculate the rebound angle (opposite angle)
                        rebound_angle = collision_normal + math.pi 
                        
                        # Treat the stationary entity as an obstacle
                        displacement_x = displacement_obstacles * math.cos(rebound_angle)
                        displacement_y = displacement_obstacles * math.sin(rebound_angle)
                        self.hitbox.left += displacement_x  
                        self.hitbox.top += displacement_y
                    else:
                        # Calculate the size ratio of the colliding entities (for example, based on widths)
                        
                        
                        # TODO: am planning to make player size bigger, also make the collision 
                        #       size not just based on width.
                        
                        # It should also dobe the entity recieving the impact that gets this size adjustment
                        #  right now its like bigger objects are bouncy, it should be more like knowckback.
                        
                        size = (self.rect.width*self.rect.height) 
                        if hasattr(self,'type'):
                            if self.type == "player" :
                                size = (self.rect.width*self.rect.height) * 3.5
                        
                                
                        size_ratio = size / (entity.rect.width*entity.rect.height)
                        
                        
                        # Calculate the displacement based on the size ratio and apply it for entities
                        displacement_entities = base_displacement_entities + base_displacement_entities * (1 + math.exp(exponent * (1 - size_ratio)))
                        
                        # Calculate relative velocity (speed) between the entities
                        relative_velocity = self.direction.magnitude() - entity.direction.magnitude()
                        
                        # Calculate the direction vector from the other entity to self
                        direction_vector = pygame.math.Vector2(self.rect.center) - pygame.math.Vector2(entity.rect.center)
                        
                        # Calculate the angle between the direction vector and the collision normal
                        collision_normal = math.atan2(direction_vector.y, direction_vector.x)
                        
                        # Calculate the rebound angle based on the collision normal and relative velocity
                        rebound_angle = collision_normal 
                        #rebound_angle = collision_normal + math.pi
                        #rebound_angle = rebound_angle % (2 * math.pi)
                        
                        # Adjust the displacement based on the relative velocity
                        displacement_entities *= 1.5 if relative_velocity > 0 else 0.5 if relative_velocity < 0 else 1
                        
                        # Determine the direction of displacement based on the movement direction
                        displacement_x = displacement_entities * math.cos(rebound_angle)
                        displacement_y = displacement_entities * math.sin(rebound_angle)
                        
                        new_left = self.hitbox.left + displacement_x
                        new_top = self.hitbox.top + displacement_y
                        
                        #Check if the new position collides with any obstacles
                        obstacles_hit = QuadTree.hit(HashableRect(pygame.Rect(new_left, new_top, self.hitbox.width, self.hitbox.height), self.id))
                        #obstacles_hit=False
                        # if hasattr(self,'type'):
                        #     if self.type == "player" :
                        #         print(f"entity.direction: {entity.direction}")
                        #         print(f"self.direction: {self.direction}")
                        #         print(f"relative_velocity: {relative_velocity}")
                        #         print(f"self.direction.magnitude() : {self.direction.magnitude() }")
                        #         print(f"entity.direction.magnitude(): {entity.direction.magnitude()}")
                        #         print(f"direction_vector: {direction_vector}")
                        #         print(f"collision_normal: {collision_normal}")
                        #         print(f"displacement_y: {displacement_y}")
                        #         print(f"displacement_x: {displacement_x}")
                            
                        
                        # If there are obstacles in the path, adjust the position
                        if obstacles_hit:
                            obstacle = next(iter(obstacles_hit))  # Get the closest obstacle
                            if self.rect.left < obstacle.left:  # Intersection with left side
                                self.hitbox.right = obstacle.left
                                self.hitbox.top = new_top
                            elif self.rect.left > obstacle.right:  # Intersection with right side
                                self.hitbox.left = obstacle.right
                                self.hitbox.top = new_top
                            elif self.rect.top < obstacle.top:  # Intersection with top side
                                self.hitbox.bottom = obstacle.top
                                self.hitbox.left = new_left
                            else:  # Intersection with bottom side
                                self.hitbox.top = obstacle.bottom
                                self.hitbox.left = new_left
                        else:
                            #Move the entity to the calculated new position
                            self.hitbox.left += displacement_x
                            self.hitbox.top += displacement_y
                            
                            
                        
                    #     if hasattr(entity, 'sprite_type'):
                    #         if entity.sprite_type== 'PolarBear':
                    #             print(f"Polarbear size_ratio :{size_ratio} ")
                    #             print(f"Polarbear direction_vector :{direction_vector} ")
                    #             print(f"Polarbear collision_normal :{collision_normal} ")
                    #             print(f"Polarbear rebound_angle:{rebound_angle} ")
                    #             print(f"Polarbear relative_velocity :{relative_velocity} ")
                    #             print(f"Polarbear displace x :{displacement_x} ")
                    #             print(f"Polarbear displace y :{displacement_y} ")
                    # # Move the entity to the calculated new position



    #@profile
    def collision__(self, QuadTree, entity_quad_tree):
        # Define displacement for collision resolution with obstacles
        displacement_obstacles = 20  # Adjust this value as needed
        
        # Define base displacement for entity collisions
        base_displacement_entities = 10  # Adjust this value as needed
        exponent = 3 # Adjust this exponent for the desired relationship
        
        # Check for nearby obstacles using the QuadTree
        nearby_obstacles = QuadTree.hit(HashableRect(self.rect, self.id))
        nearby_entities = entity_quad_tree.hit(HashableRect(self.rect, self.id))
        
        # Iterate over nearby obstacles (walls)
        for obstacle in nearby_obstacles:
            # Calculate the angle of collision relative to the entity's movement direction
            angle_radians = math.atan2(self.direction.y, self.direction.x)
            angle_degrees = math.degrees(angle_radians)
            
            # Calculate the angle between the entity's direction and the collision normal
            collision_normal = math.atan2(obstacle.rect.centery - self.rect.centery, obstacle.rect.centerx - self.rect.centerx)
            
            # Calculate the rebound angle (opposite angle)
            rebound_angle = collision_normal + math.pi 
            
            # Adjust the position of the entity based on the rebound angle for obstacles
            self.hitbox.left += displacement_obstacles * math.cos(rebound_angle)
            self.hitbox.top += displacement_obstacles * math.sin(rebound_angle)
        
        # If not colliding with a wall, handle entity collisions
        if not nearby_obstacles:
            for entity in nearby_entities:
                # Calculate the size ratio of the colliding entities (for example, based on widths)
                
                #print(f"size ratio : {size_ratio}")
                # Calculate the displacement based on the size ratio and apply it for entities
                
                
                if hasattr(self,'type'):
                    if self.type == "player" :
                        self_size = self.rect.width*20
                        #print(self.rect.size)
                    else: self_size = self.rect.width
                        #print(f"entity.direction: {entity.direction}")
                size_ratio = self_size / entity.rect.width
                
                displacement_entities = base_displacement_entities + base_displacement_entities * (1 + math.exp(-exponent * (1 - size_ratio)))
                #print(displacement_entities)
                # Calculate relative velocity (speed) between the entities
                relative_velocity = self.direction.magnitude() - entity.direction.magnitude()
                # Calculate the direction vector from the other entity to self
                
                
                
                
                
                #### Here if the other entity is stationary, we just get the direction of self as with wall
                #     Regardless, this must be what is going wrong.
                
                direction_vector = pygame.math.Vector2(self.rect.center) - pygame.math.Vector2(entity.rect.center)
                
                # Calculate the angle between the direction vector and the collision normal
                collision_normal = math.atan2(direction_vector.y, direction_vector.x)
                
                # Calculate the rebound angle based on the collision normal and relative velocity
                rebound_angle = collision_normal + math.pi
               # # Adjust the displacement based on the relative velocity
                # if relative_velocity > 0:  # Entities are moving towards each other
                #     displacement_entities *= 1.5  # Increase displacement
                # elif relative_velocity < 0:  # Entities are moving away from each other
                #     displacement_entities *= 0.5  # Decrease displacement
                
                
                displacement_y = displacement_entities * math.sin(rebound_angle)
                displacement_x = displacement_entities * math.cos(rebound_angle)
                     
                    # if math.sin(rebound_angle) > 0:
                    #     displacement_y *= -1
                    
                    # # # Adjust displacement_x based on the sign of math.cos(rebound_angle)
                    # if math.cos(rebound_angle) > 0:
                    #     displacement_x *= -1
               
                    # #displacement_x *= abs(math.sin(collision_normal))
                    # #displacement_y *= abs(math.cos(collision_normal))
           
                # Determine which vertex to adjust based on the rebound angle
                #if rebound_angle < math.pi:  
                #new_left = self.rect.left + displacement_x
                #new_top = self.rect.top + displacement_y
                #else:  # Collision from the left or above
                #    new_left = self.rect.left - displacement_x
                #    new_top = self.rect.top - displacement_y            
               
                # new_left = self.rect.left + displacement_x
                # new_top = self.rect.top + displacement_y
                
                # Check if the new position collides with any obstacles
                # obstacles_hit = QuadTree.hit(HashableRect(pygame.Rect(new_left, new_top, self.hitbox.width, self.hitbox.height), self.id))
                # obstacles_hit=False
                # if hasattr(self,'type'):
                #     if self.type == "player" :
                #         print(f"entity.direction: {entity.direction}")
                #         print(f"self.direction: {self.direction}")
                #         print(f"relative_velocity: {relative_velocity}")
                #         print(f"self.direction.magnitude() : {self.direction.magnitude() }")
                #         print(f"entity.direction.magnitude(): {entity.direction.magnitude()}")
                #         print(f"direction_vector: {direction_vector}")
                #         print(f"collision_normal: {collision_normal}")
                #         print(f"displacement_y: {displacement_y}")
                #         print(f"displacement_x: {displacement_x}")
                    
                
                # # If there are obstacles in the path, adjust the position
                # if obstacles_hit:
                #     obstacle = next(iter(obstacles_hit))  # Get the closest obstacle
                #     if self.rect.left < obstacle.left:  # Intersection with left side
                #         self.hitbox.right = obstacle.left
                #         self.hitbox.top = new_top
                #     elif self.rect.left > obstacle.right:  # Intersection with right side
                #         self.hitbox.left = obstacle.right
                #         self.hitbox.top = new_top
                #     elif self.rect.top < obstacle.top:  # Intersection with top side
                #         self.hitbox.bottom = obstacle.top
                #         self.hitbox.left = new_left
                #     else:  # Intersection with bottom side
                #         self.hitbox.top = obstacle.bottom
                #         self.hitbox.left = new_left
                #else:
                    # Move the entity to the calculated new position
                self.hitbox.left += displacement_x
                self.hitbox.top += displacement_y
    
    def check_effects(self, effect_quad_trees):
        """
        Check if entity is colliding with any effect areas.
        Effects don't block movement - they just detect presence and apply properties.
        Uses two-phase collision: broad phase (rect) then narrow phase (mask-on-mask).
        Same pattern as entity/obstacle collisions for consistency.
        """
        if not effect_quad_trees:
            return
        
        # Track currently colliding effect areas
        current_effect_area_ids = set()
        
        # BROAD PHASE: Use rect for quad tree query (same as entity/obstacle collisions)
        entity_rect = HashableRect(self.rect, self.id)
        
        # Check each effect layer's quad tree
        for layer_name, effect_tree in effect_quad_trees.items():
            nearby_effects = effect_tree.hit(entity_rect)
            
            # NARROW PHASE: For each nearby effect, check mask-on-mask collision
            for effect_area in nearby_effects:
                do_collision = True  # Assume collision from broad phase
                
                # DEBUG: Log mask status for effects
                log_path = os.path.join(os.path.dirname(__file__), "mask_debug.log")
                with open(log_path, "a") as f:
                    f.write(f"Effect collision - self.mask: {self.mask is not None}, effect_area.mask: {getattr(effect_area, 'mask', None) is not None}\n")
                    if self.mask:
                        f.write(f"  self.mask size: {self.mask.get_size() if self.mask else 'None'}\n")
                    if hasattr(effect_area, 'mask') and effect_area.mask:
                        f.write(f"  effect_area.mask size: {effect_area.mask.get_size() if effect_area.mask else 'None'}\n")
                
                # If both have masks, do precise mask-on-mask check (same as entity collisions)
                if self.mask and effect_area.mask:
                    # Calculate offset using rect positions (same as entity collisions)
                    # IMPORTANT: Both masks are created from surfaces starting at (0,0)
                    # The rect positions represent where those surfaces are in world space
                    dx = effect_area.rect.x - self.rect.x
                    dy = effect_area.rect.y - self.rect.y
                    
                    # DEBUG: Log detailed rect and mask info
                    with open(log_path, "a") as f:
                        f.write(f"  Entity rect: {self.rect} (x={self.rect.x}, y={self.rect.y}, w={self.rect.width}, h={self.rect.height})\n")
                        f.write(f"  Effect rect: {effect_area.rect} (x={effect_area.rect.x}, y={effect_area.rect.y}, w={effect_area.rect.width}, h={effect_area.rect.height})\n")
                        f.write(f"  Entity mask size: {self.mask.get_size()}, Effect mask size: {effect_area.mask.get_size()}\n")
                        f.write(f"  Entity rect size: ({self.rect.width}, {self.rect.height}), Effect rect size: ({effect_area.rect.width}, {effect_area.rect.height})\n")
                        f.write(f"  Offset (dx, dy): ({dx}, {dy})\n")
                        # Check if mask size matches rect size (they should match)
                        entity_mask_size = self.mask.get_size()
                        effect_mask_size = effect_area.mask.get_size()
                        if entity_mask_size != (self.rect.width, self.rect.height):
                            f.write(f"  WARNING: Entity mask size {entity_mask_size} != rect size ({self.rect.width}, {self.rect.height})\n")
                        if effect_mask_size != (effect_area.rect.width, effect_area.rect.height):
                            f.write(f"  WARNING: Effect mask size {effect_mask_size} != rect size ({effect_area.rect.width}, {effect_area.rect.height})\n")
                    
                    overlap = self.mask.overlap_area(effect_area.mask, (dx, dy))
                    
                    # DEBUG: Log overlap result
                    with open(log_path, "a") as f:
                        f.write(f"  Mask overlap check - dx: {dx}, dy: {dy}, overlap: {overlap}\n")
                        # Also try the reverse offset to see if that makes a difference
                        reverse_overlap = effect_area.mask.overlap_area(self.mask, (-dx, -dy))
                        f.write(f"  Reverse overlap check (effect->entity): overlap: {reverse_overlap}\n")
                    
                    if overlap == 0:
                        do_collision = False  # No overlap, no collision
                        # DEBUG: Log when mask filter works
                        with open(log_path, "a") as f:
                            f.write(f"  Mask filter worked - no collision (overlap == 0)\n")
                    else:
                        # DEBUG: Log when collision is confirmed
                        with open(log_path, "a") as f:
                            f.write(f"  Mask collision confirmed - overlap: {overlap} pixels, effect_id: {effect_area._id}\n")
                else:
                    # DEBUG: Log why mask check was skipped
                    with open(log_path, "a") as f:
                        f.write(f"  Skipping mask check for effect - using rect collision\n")
                
                if do_collision:
                    effect_area_id = effect_area._id
                    current_effect_area_ids.add(effect_area_id)
                    
                    # DEBUG: Log which effects are currently colliding
                    with open(log_path, "a") as f:
                        f.write(f"  Effect in current_effect_area_ids: {effect_area_id}\n")
                    
                    # If effect not already active, create and apply it
                    if effect_area_id not in self.active_effects:
                        # Look up effect class from registry based on properties
                        effect_instance = None
                        for prop_key, effect_class in EFFECT_REGISTRY.items():
                            if prop_key in effect_area.properties:
                                effect_instance = effect_class(effect_area.properties)
                                break
                        
                        if effect_instance:
                            self.active_effects[effect_area_id] = effect_instance
                            effect_instance.apply(self)
                            # DEBUG: Log effect application with velocity
                            with open(log_path, "a") as f:
                                f.write(f"  Effect APPLIED: {effect_area_id}, velocity: {self.velocity}\n")
        
        # Remove effects that are no longer colliding
        effects_to_remove = []
        for effect_area_id, effect_instance in self.active_effects.items():
            if effect_area_id not in current_effect_area_ids:
                # Check if effect should persist after exit
                if not effect_instance.should_persist_after_exit():
                    effect_instance.remove(self)
                    effects_to_remove.append(effect_area_id)
                    # DEBUG: Log effect removal with timing
                    log_path = os.path.join(os.path.dirname(__file__), "mask_debug.log")
                    with open(log_path, "a") as f:
                        f.write(f"  Effect REMOVED: {effect_area_id} (no longer colliding, velocity: {self.velocity})\n")
                    # Apply normal friction when exiting (if slippery)
                    if hasattr(effect_instance, 'slippery_factor'):
                        # Velocity persists, normal friction will handle it
                        pass
        
        # Remove effects that shouldn't persist
        for effect_area_id in effects_to_remove:
            del self.active_effects[effect_area_id]
        
        # DEBUG: Log active effects and velocity after cleanup
        log_path = os.path.join(os.path.dirname(__file__), "mask_debug.log")
        with open(log_path, "a") as f:
            if self.active_effects:
                f.write(f"  Active effects after cleanup: {list(self.active_effects.keys())}, velocity: {self.velocity}\n")
            elif effects_to_remove:
                f.write(f"  All effects removed, velocity: {self.velocity}\n")
          
    def line_rect_intersection(start_point, end_point, rect):
        x1, y1 = start_point
        x2, y2 = end_point
    
        # Determine the side of the rectangle the line intersects with
        if x1 < rect.left:  # Intersection with left side
            x = rect.left
            y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        elif x1 > rect.right:  # Intersection with right side
            x = rect.right
            y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        elif y1 < rect.top:  # Intersection with top side
            y = rect.top
            x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
        else:  # Intersection with bottom side
            y = rect.bottom
            x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
    
        return x, y
          
              
    ###@profile
    def collision_old3(self, direction):
        for sprite in self.obstacle_sprites:
            # Calculate the distance between the entity and the obstacle sprite
            #print(f"sprite.rect.center:{sprite.rect.center}, self.hitbox.center : {self.hitbox.center}")
            #distance = pygame.math.Vector2(sprite.rect.center) - pygame.math.Vector2(self.hitbox.center)
            # Check if the obstacle is within the maximum collision distance
            #if distance.length() <= self.max_collision_distance.length():
                         # Calculate the distance between the entity and the obstacle sprite
            dx = sprite.rect.centerx - self.hitbox.centerx
            dy = sprite.rect.centery - self.hitbox.centery
            if min(dx,dy) < 100:
            #print(dy)
            #print(dx)
            #distance_squared = dx ** 2 + dy ** 2
            #print(distance_squared)
            # Check if the obstacle is within the maximum collision distance
            #if distance_squared <= self.max_collision_distance_squared:
                if sprite.hitbox.colliderect(self.hitbox):
                    if direction == "Horizontal":
                        if self.direction.x > 0:  # Moving Right
                            self.hitbox.right = sprite.hitbox.left
                        elif self.direction.x < 0:  # Moving Left
                            self.hitbox.left = sprite.hitbox.right
                    
                    elif direction == "Vertical":
                        if self.direction.y > 0:  # Moving Down
                            self.hitbox.bottom = sprite.hitbox.top
                        elif self.direction.y < 0:  # Moving Up
                            self.hitbox.top = sprite.hitbox.bottom
                    return
                
    ###@profile
    def collision_old2(self, direction):
        if direction == "Horizontal":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.x > 0: # Moving Right
                        self.hitbox.right = sprite.hitbox.left
                    elif self.direction.x < 0: # Moving Left
                        self.hitbox.left = sprite.hitbox.right
                    return                  
        if direction == "Vertical":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.y > 0: # Moving Down
                        self.hitbox.bottom = sprite.hitbox.top
                    elif self.direction.y < 0: # Moving Up
                        self.hitbox.top = sprite.hitbox.bottom
                    return
    ###@profile
    def collision_old(self, direction):
        if direction == "Horizontal":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.x > 0: # Moving Right
                        self.hitbox.right = sprite.hitbox.left
                    if self.direction.x < 0: # Moving Left
                        self.hitbox.left = sprite.hitbox.right
                        
        if direction == "Vertical":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.y > 0: # Moving Down
                        self.hitbox.bottom = sprite.hitbox.top
                    if self.direction.y < 0: # Moving Up
                        self.hitbox.top = sprite.hitbox.bottom

    def wave_value(self):
        value = sin(pygame.time.get_ticks())
        if value >= 0:
            return 255
        else:
            return 0
