import pygame
from ImageCache import ImageCache
import legion_ui as L


class AttackSlot:
    def __init__(self, rect, attack_type="general", angle=0, icon_path = None):
        self.rect = rect
        self.attack_type = attack_type
        self.angle = angle
        self.attack = None
        self.icon_path = icon_path
        # Held by ImageCache for the run, so its id is stable and its fitted copy can be kept.
        self.attack_icon = ImageCache.load_image(self.icon_path) if self.icon_path else None


class AttackSelection:

    def __init__(self, player, input_manager):
        self.visible = False
        self.slots = []
        self.input_manager = input_manager
        self.player = player
        self.held_icon = None 


        # Setup for magic attack slots on the left
        base_x, base_y = 50, 50
        max_magic_slots = 3  # Maximum of 3 magic attack slots

        self.selected_row = 0 
        self.selected_col = 0
        self.in_magic_slots = True
        self.grid_columns = 4  # 4x4 grid on the right
        self.grid_rows = 4
        self.magic_slots = 3  # 3 magic slots on the left

       
        # Create slots for the player's magic attacks or empty slots if less than 3
        for i in range(max_magic_slots):
            if i < len(player.magic_available):
                magic_key = list(player.magic_available.keys())[i]
                magic_info = player.magic_available[magic_key]
                icon_path = magic_info['graphic']
            else:
                icon_path = None  # Path to an empty slot image or None

            self.slots.append(AttackSlot(pygame.Rect(base_x + i * 110, base_y, 100, 100), "magic", 0, icon_path))

        # Setup for magic attack grid (4x4) or any other UI elements
        grid_x, grid_y = 320, 100
        for i in range(4):  # Rows
            for j in range(4):  # Columns
                x = grid_x + j * 110
                y = grid_y + i * 110
                self.slots.append(AttackSlot(pygame.Rect(x, y, 100, 100)))

    def toggle_visibility(self):
        self.visible = not self.visible

    def display(self, backend):
        """A framed panel: the magic slots in a row on the left, the 4 x 4 grid on the right,
        each in the slot frame with its attack's icon."""
        if not self.visible:
            return
        kit = L.kit_for(backend)
        side, grid_side, gap = kit.px(96), kit.px(80), kit.px(10)
        pad = kit.px(30)
        kicker = kit.label("Attacks", "body", 13, L.GOLD, spacing=0.22, upper=True)
        title = kit.label("Magic", "display", 32, L.GOLD)
        hint = kit.label("Arrows move \u00b7 Enter picks up and sets down \u00b7 Esc closes", "body", 12, L.GOLD, spacing=0.06)
        label_h = kit.font("body", 12).get_height() + kit.px(8)
        row_w = self.magic_slots * side + (self.magic_slots - 1) * gap
        grid_w = self.grid_columns * grid_side + (self.grid_columns - 1) * gap
        grid_h = self.grid_rows * grid_side + (self.grid_rows - 1) * gap
        width = 2 * pad + max(row_w + kit.px(40) + grid_w, hint.get_width())
        height = 2 * pad + kicker.get_height() + title.get_height() + kit.px(12) + label_h + grid_h + kit.px(14) + hint.get_height()
        panel = pygame.Rect(0, 0, width, height)
        panel.center = (kit.width // 2, kit.height // 2)
        L.draw(backend, kit.panel(panel.w, panel.h), panel.topleft)
        x, y = panel.x + pad, panel.y + pad
        L.draw(backend, kicker, (x, y))
        L.draw(backend, title, (x, y + kicker.get_height()))
        y += kicker.get_height() + title.get_height() + kit.px(12)
        grid_x = x + row_w + kit.px(40)
        L.draw(backend, kit.label("Equipped", "body", 12, L.GOLD, spacing=0.14, upper=True), (x, y))
        L.draw(backend, kit.label("Stored", "body", 12, L.GOLD, spacing=0.14, upper=True), (grid_x, y))
        y += label_h
        for i, slot in enumerate(self.slots):
            if i < self.magic_slots:
                slot.rect = pygame.Rect(x + i * (side + gap), y, side, side)
            else:
                k = i - self.magic_slots
                row, col = divmod(k, self.grid_columns)
                slot.rect = pygame.Rect(grid_x + col * (grid_side + gap), y + row * (grid_side + gap), grid_side, grid_side)
            r = slot.rect
            selected = self.is_slot_selected(i)
            if selected:
                edge, glow = kit.highlight(r.w, r.h)
                L.draw(backend, edge, (r.x - glow, r.y - glow))
            L.draw(backend, kit.slot(r.w, r.h), r.topleft)
            if slot.attack_icon is not None:
                icon = kit.fitted(slot.attack_icon, round(r.w * 0.78), round(r.h * 0.78), id(slot.attack_icon))
                L.draw(backend, icon, (r.centerx - icon.get_width() // 2, r.centery - icon.get_height() // 2))
            if selected and self.held_icon is not None:
                held = kit.fitted(self.held_icon, kit.px(30), kit.px(30), id(self.held_icon))
                L.draw(backend, held, (r.right - held.get_width() // 2, r.y - held.get_height() // 2))
        L.draw(backend, hint, (x, panel.bottom - pad - hint.get_height()))

    def is_slot_selected(self, index):
        if self.in_magic_slots and index < self.magic_slots:
            return index == self.selected_row
        elif not self.in_magic_slots and index >= self.magic_slots:
            grid_index = index - self.magic_slots
            row = grid_index // self.grid_columns
            col = grid_index % self.grid_columns
            return row == self.selected_row and col == self.selected_col
        return False


    def get_current_slot_index(self):
        if self.in_magic_slots:
            return self.selected_row  # Magic slots index directly matches selected_row
        else:
            # Calculate index for the grid
            return self.magic_slots + self.selected_row * self.grid_columns + self.selected_col


    def input(self):

        if self.in_magic_slots:
            if self.input_manager.is_key_just_pressed(pygame.K_RIGHT) and self.selected_row < self.magic_slots - 1:
                # Navigate right within the magic slots
                self.selected_row += 1
            elif self.input_manager.is_key_just_pressed(pygame.K_LEFT) and self.selected_row > 0:
                # Navigate left within the magic slots
                self.selected_row -= 1
            elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT) and self.selected_row == self.magic_slots - 1:
                # Move to the grid on the right, top-left corner
                self.in_magic_slots = False
                self.selected_row = 0
                self.selected_col = 0
        # Handle input within the grid
        else:
            if self.input_manager.is_key_just_pressed(pygame.K_DOWN):
                self.selected_row = min(self.selected_row + 1, self.grid_rows - 1)
            elif self.input_manager.is_key_just_pressed(pygame.K_UP):
                self.selected_row = max(0, self.selected_row - 1)
            elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT):
                self.selected_col = min(self.selected_col + 1, self.grid_columns - 1)
            elif self.input_manager.is_key_just_pressed(pygame.K_LEFT):
                self.selected_col = max(0, self.selected_col - 1)
                if self.selected_col == 0 and self.input_manager.is_key_just_pressed(pygame.K_LEFT):
                    # Move back to the magic slots, right-most slot
                    self.in_magic_slots = True
                    self.selected_row = self.magic_slots - 1
        
        if self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            index = self.get_current_slot_index()
            if self.held_icon is None and self.slots[index].attack_icon:
                # Pick up the icon
                self.held_icon = self.slots[index].attack_icon
                self.slots[index].attack_icon = None  # Empty the slot
            elif self.held_icon and not self.slots[index].attack_icon:
                # Drop the icon in the empty slot
                self.slots[index].attack_icon = self.held_icon
                self.held_icon = None  # No icon is held now
                
        
        # Exit with alt q or esc
        current_time = pygame.time.get_ticks()
        if self.input_manager.is_key_just_pressed(pygame.K_ESCAPE) or \
            (self.input_manager.is_key_pressed(pygame.K_LALT) or self.input_manager.is_key_pressed(pygame.K_RALT)) and \
            self.input_manager.is_key_just_pressed(pygame.K_q):
            if current_time - self.player.last_q_press_time > 500:
                self.player.level.toggle_attack_selection()
                self.player.last_q_press_time = current_time

