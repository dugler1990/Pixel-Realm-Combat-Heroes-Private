import pygame
from ImageCache import ImageCache
from game_logging import get_debug_logger

_player_item_log = get_debug_logger("player_item")

# Max stack size per slot for stackable items (consumables).
MAX_STACK_PER_ITEM = 99

BODY_SLOT_COUNT = 9
BACKPACK_ROWS = 4
BACKPACK_COLS = 3
BACKPACK_COUNT = BACKPACK_ROWS * BACKPACK_COLS
BELT_SLOT_COUNT = 4

FOCUS_BODY = 0
FOCUS_BACKPACK = 1
FOCUS_BELT = 2

_BELT_HUD_FONT = None
_BELT_LABEL_SURFACES = None
_BELT_QTY_SURFACES = {}


def _belt_hud_font():
    global _BELT_HUD_FONT
    if _BELT_HUD_FONT is None:
        _BELT_HUD_FONT = pygame.font.Font(None, 16)
    return _BELT_HUD_FONT


def _belt_label_surfaces():
    global _BELT_LABEL_SURFACES
    if _BELT_LABEL_SURFACES is None:
        font = _belt_hud_font()
        _BELT_LABEL_SURFACES = [
            font.render(str(i + 1), True, (180, 180, 180))
            for i in range(BELT_SLOT_COUNT)
        ]
    return _BELT_LABEL_SURFACES


def _belt_qty_surface(quantity):
    qty = int(quantity)
    cached = _BELT_QTY_SURFACES.get(qty)
    if cached is None:
        cached = _belt_hud_font().render(str(qty), True, (255, 255, 255))
        _BELT_QTY_SURFACES[qty] = cached
    return cached


def _item_is_stackable(item):
    return getattr(item, "effect_type", None) == "consumable"


def _can_place_on_belt(item):
    return (
        getattr(item, "belt_allowed", False)
        and getattr(item, "effect_type", None) == "consumable"
    )


def _clear_slot_visual(slot):
    slot._cached_item_key = None
    slot._cached_item_surface = None


class InventorySlot:
    def __init__(self, rect, slot_type="general", angle=0):
        self.rect = rect
        self.slot_type = slot_type
        self.angle = angle
        self.item = None
        self.quantity = 0
        self._cached_item_key = None
        self._cached_item_surface = None

    def _get_cached_item_surface(self):
        if self.item is None:
            self._cached_item_key = None
            self._cached_item_surface = None
            return None

        item_path = getattr(self.item, "image_path", None)
        if not item_path:
            return None

        cache_key = (item_path, self.rect.width, self.rect.height, self.angle)
        if cache_key != self._cached_item_key:
            item_image = pygame.image.load(item_path).convert_alpha()
            item_image = pygame.transform.scale(
                item_image, (self.rect.width, self.rect.height)
            )
            if self.angle != 0:
                item_image = pygame.transform.rotate(item_image, self.angle)
            self._cached_item_key = cache_key
            self._cached_item_surface = item_image

        return self._cached_item_surface

    def draw(self, screen, selected=False, count_font=None, locked=False, dimmed=False):
        if self.angle != 0:
            slot_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
            if self.slot_type == "belt":
                color = (200, 160, 80)
            elif self.slot_type == "waist":
                color = (160, 120, 200)
            else:
                color = (255, 255, 255) if self.slot_type == "general" else (0, 255, 0)
            pygame.draw.rect(slot_surface, color, (0, 0, self.rect.width, self.rect.height))

            rotated_image = pygame.transform.rotate(slot_surface, self.angle)
            screen.blit(rotated_image, rotated_image.get_rect(center=self.rect.center))
        else:
            if self.slot_type == "belt":
                color = (200, 160, 80)
            else:
                color = (255, 255, 255) if self.slot_type == "general" else (0, 255, 0)
            pygame.draw.rect(screen, color, self.rect, 2)

        if selected:
            pygame.draw.rect(screen, (0, 200, 100), self.rect, 3)

        item_image = self._get_cached_item_surface()
        if item_image is not None:
            if self.angle != 0:
                screen.blit(item_image, item_image.get_rect(center=self.rect.center))
            else:
                screen.blit(item_image, self.rect.topleft)

        if count_font is not None and self.item is not None and self.quantity > 1:
            txt = count_font.render(str(self.quantity), True, (255, 255, 255))
            br = self.rect.bottomright
            screen.blit(txt, (br[0] - txt.get_width() - 2, br[1] - txt.get_height() - 2))

        if locked or dimmed:
            ov = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
            ov.fill((40, 40, 40, 160))
            screen.blit(ov, self.rect.topleft)


def draw_belt_hud(screen, player, inventory):
    """Bottom-center belt bar during gameplay (inventory closed)."""
    if not getattr(player, "has_belt", False):
        return
    cap = getattr(player, "belt_capacity", 0)
    if cap <= 0:
        return
    slot_w, slot_h = 36, 36
    gap = 8
    total_w = BELT_SLOT_COUNT * slot_w + (BELT_SLOT_COUNT - 1) * gap
    W, H = screen.get_size()
    x0 = (W - total_w) // 2
    y0 = H - slot_h - 18
    label_surfaces = _belt_label_surfaces()
    for i in range(BELT_SLOT_COUNT):
        r = pygame.Rect(x0 + i * (slot_w + gap), y0, slot_w, slot_h)
        locked = i >= cap
        src = inventory.slots[inventory.belt_start_index + i]
        pygame.draw.rect(screen, (200, 160, 80), r, 2)
        if locked:
            ov = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            ov.fill((40, 40, 40, 180))
            screen.blit(ov, r.topleft)
        elif src.item is not None and src.quantity > 0:
            ip = getattr(src.item, "image_path", None)
            if ip:
                img = ImageCache.load_scaled(ip, (slot_w - 4, slot_h - 4))
                screen.blit(img, (r.x + 2, r.y + 2))
            if src.quantity > 1:
                t = _belt_qty_surface(src.quantity)
                screen.blit(t, (r.right - t.get_width() - 2, r.bottom - t.get_height() - 2))
        lbl = label_surfaces[i]
        screen.blit(lbl, (r.centerx - lbl.get_width() // 2, r.y - 14))


class Inventory:
    def __init__(self, player, input_manager):
        self.visible = False
        self.slots = []
        self.input_manager = input_manager
        self.player = player

        base_x, base_y = 50, 50
        slot_width, slot_height = 60, 60

        self.slots.append(InventorySlot(pygame.Rect(base_x + 70, base_y, 50, 50), "helmet"))
        self.slots.append(InventorySlot(pygame.Rect(base_x, base_y + 60, 180, 120), "armor"))

        arm_width, arm_height = 20, 140
        self.slots.append(InventorySlot(pygame.Rect(base_x - 25, base_y + 100, arm_width, arm_height), "arm", angle=30))
        self.slots.append(InventorySlot(pygame.Rect(base_x + 185, base_y + 100, arm_width, arm_height), "arm", angle=-30))

        self.slots.append(InventorySlot(pygame.Rect(base_x - 10, base_y + 210, 45, 135), "weapon"))
        self.slots.append(InventorySlot(pygame.Rect(base_x + 145, base_y + 210, 45, 135), "weapon"))

        self.slots.append(InventorySlot(pygame.Rect(base_x - 20, base_y + 355, 80, 40), "boots"))
        self.slots.append(InventorySlot(pygame.Rect(base_x + 120, base_y + 355, 80, 40), "boots"))
        self.slots.append(InventorySlot(pygame.Rect(base_x + 70, base_y + 300, 50, 48), "waist"))

        self.body_start_index = 0
        self.waist_slot_index = self.body_start_index + BODY_SLOT_COUNT - 1
        self.backpack_start_index = BODY_SLOT_COUNT

        backpack_x, backpack_y = 320, 100
        for i in range(BACKPACK_ROWS):
            for j in range(BACKPACK_COLS):
                x = backpack_x + j * (slot_width + 10)
                y = backpack_y + i * (slot_height + 10)
                self.slots.append(InventorySlot(pygame.Rect(x, y, slot_width, slot_height)))

        self.belt_start_index = self.backpack_start_index + BACKPACK_COUNT
        belt_y = 500
        belt_x0 = 206
        belt_w, belt_h = 44, 44
        for i in range(BELT_SLOT_COUNT):
            self.slots.append(
                InventorySlot(pygame.Rect(belt_x0 + i * (belt_w + 4), belt_y, belt_w, belt_h), "belt")
            )

        self.selected_backpack_index = 0
        self.body_index = 0
        self.belt_index = 0
        self.focus_region = FOCUS_BACKPACK

        self.hand_item = None
        self.hand_qty = 0

        self._count_font = pygame.font.Font(None, 18)
        self._gold_font = pygame.font.Font(None, 22)

    def toggle_visibility(self):
        self.visible = not self.visible

    def _get_focused_slot(self):
        if self.focus_region == FOCUS_BODY:
            return self.slots[self.body_start_index + self.body_index]
        if self.focus_region == FOCUS_BACKPACK:
            return self.slots[self.backpack_start_index + self.selected_backpack_index]
        return self.slots[self.belt_start_index + self.belt_index]

    def _belt_slot_locked(self, belt_idx):
        return belt_idx >= getattr(self.player, "belt_capacity", 0)

    def _draw_hand_ghost(self, screen):
        if self.hand_item is None or self.hand_qty <= 0:
            return
        slot = self._get_focused_slot()
        cx, cy = slot.rect.center
        path = getattr(self.hand_item, "image_path", None)
        if not path:
            return
        img = pygame.image.load(path).convert_alpha()
        img = pygame.transform.scale(img, (32, 32))
        screen.blit(img, (cx + 24, cy - 8))
        if self.hand_qty > 1:
            t = self._count_font.render(str(self.hand_qty), True, (255, 220, 100))
            screen.blit(t, (cx + 48, cy + 8))

    def display(self, screen):
        if self.visible:
            inventory_area = pygame.Rect(20, 20, 550, 560)
            transparent_surface = pygame.Surface((inventory_area.width, inventory_area.height), pygame.SRCALPHA)
            transparent_surface.fill((128, 128, 128, 100))
            screen.blit(transparent_surface, inventory_area.topleft)

            cap = getattr(self.player, "belt_capacity", 0)

            for i, slot in enumerate(self.slots):
                sel = False
                if i < self.backpack_start_index:
                    bi = i - self.body_start_index
                    sel = self.focus_region == FOCUS_BODY and bi == self.body_index
                elif i < self.belt_start_index:
                    bi = i - self.backpack_start_index
                    sel = self.focus_region == FOCUS_BACKPACK and bi == self.selected_backpack_index
                else:
                    bi = i - self.belt_start_index
                    sel = self.focus_region == FOCUS_BELT and bi == self.belt_index

                locked = False
                dimmed = False
                if slot.slot_type == "belt":
                    locked = self._belt_slot_locked(bi)
                    dimmed = locked

                slot.draw(
                    screen,
                    selected=sel,
                    count_font=self._count_font,
                    locked=locked,
                    dimmed=dimmed,
                )

            self._draw_hand_ghost(screen)

            gold_label = self._gold_font.render(
                f"Gold: {getattr(self.player, 'gold', 0)}", True, (255, 215, 0)
            )
            gx = inventory_area.x + 24
            gy = inventory_area.bottom - gold_label.get_height() - 14
            screen.blit(gold_label, (gx, gy))

    def input(self):
        current_time = pygame.time.get_ticks()
        if self.input_manager.is_key_just_pressed(pygame.K_i):
            if current_time - self.player.last_i_press_time > 500:
                self.player.level.toggle_inventory()
                self.player.last_i_press_time = current_time
            return

        if not self.visible:
            return

        if self.input_manager.is_key_just_pressed(pygame.K_TAB):
            if getattr(self.player, "has_belt", False):
                self.focus_region = (self.focus_region + 1) % 3
            else:
                self.focus_region = FOCUS_BACKPACK if self.focus_region == FOCUS_BODY else FOCUS_BODY
            return

        if self.focus_region == FOCUS_BODY:
            if self.input_manager.is_key_just_pressed(pygame.K_LEFT):
                self.body_index = (self.body_index - 1) % BODY_SLOT_COUNT
            elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT):
                self.body_index = (self.body_index + 1) % BODY_SLOT_COUNT
        elif self.focus_region == FOCUS_BACKPACK:
            idx = self.selected_backpack_index
            row, col = idx // BACKPACK_COLS, idx % BACKPACK_COLS
            if self.input_manager.is_key_just_pressed(pygame.K_UP) and row > 0:
                self.selected_backpack_index = idx - BACKPACK_COLS
            elif self.input_manager.is_key_just_pressed(pygame.K_DOWN) and row < BACKPACK_ROWS - 1:
                self.selected_backpack_index = idx + BACKPACK_COLS
            elif self.input_manager.is_key_just_pressed(pygame.K_LEFT) and col > 0:
                self.selected_backpack_index = idx - 1
            elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT) and col < BACKPACK_COLS - 1:
                self.selected_backpack_index = idx + 1
        elif self.focus_region == FOCUS_BELT and getattr(self.player, "has_belt", False):
            if self.input_manager.is_key_just_pressed(pygame.K_LEFT):
                self.belt_index = (self.belt_index - 1) % BELT_SLOT_COUNT
            elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT):
                self.belt_index = (self.belt_index + 1) % BELT_SLOT_COUNT

        if self.input_manager.is_key_just_pressed(pygame.K_u):
            if self.focus_region == FOCUS_BACKPACK:
                self.use_selected_backpack_item()
            return

        if self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            if self.hand_item is None:
                self._lift_from_slot(self._get_focused_slot())
            else:
                self._place_or_swap(self._get_focused_slot())

    def _lift_from_slot(self, slot):
        if slot.item is None or slot.quantity <= 0:
            return
        if slot.slot_type == "belt" and self._belt_slot_locked(self.slots.index(slot) - self.belt_start_index):
            return
        self.hand_item = slot.item
        self.hand_qty = slot.quantity
        slot.item = None
        slot.quantity = 0
        _clear_slot_visual(slot)
        self.sync_belt_from_waist()

    def sync_belt_from_waist(self):
        prev = getattr(self.player, "has_belt", False)
        slot = self.slots[self.waist_slot_index]
        it = slot.item
        if (
            it is not None
            and slot.quantity > 0
            and getattr(it, "effect_type", None) == "belt_equip"
        ):
            eff = getattr(it, "effect", None) or {}
            n = int(eff.get("belt_slots", 1))
            self.player.has_belt = True
            self.player.belt_capacity = min(BELT_SLOT_COUNT, max(0, n))
        else:
            self.player.has_belt = False
            self.player.belt_capacity = 0
            if prev:
                self.dump_belt_slots_to_backpack()
        if not self.player.has_belt and self.focus_region == FOCUS_BELT:
            self.focus_region = FOCUS_BACKPACK

    def dump_belt_slots_to_backpack(self):
        for i in range(BELT_SLOT_COUNT):
            slot = self.slots[self.belt_start_index + i]
            if slot.item is None or slot.quantity <= 0:
                continue
            target_qty = slot.quantity
            moved = 0
            for _ in range(target_qty):
                if not self.add_item(slot.item):
                    break
                moved += 1
            slot.quantity -= moved
            if slot.quantity <= 0:
                slot.item = None
                slot.quantity = 0
                _clear_slot_visual(slot)

    def _can_place_in_slot(self, slot, item):
        if slot.slot_type == "waist":
            return getattr(item, "effect_type", None) == "belt_equip"
        if slot.slot_type == "belt":
            bidx = self.slots.index(slot) - self.belt_start_index
            if self._belt_slot_locked(bidx):
                return False
            return _can_place_on_belt(item)
        return True

    def _place_or_swap(self, slot):
        if self.hand_item is None or self.hand_qty <= 0:
            return
        if not self._can_place_in_slot(slot, self.hand_item):
            return

        if slot.item is None:
            slot.item = self.hand_item
            slot.quantity = self.hand_qty
            self.hand_item = None
            self.hand_qty = 0
            _clear_slot_visual(slot)
            self.sync_belt_from_waist()
            return

        if (
            slot.item.item_id == self.hand_item.item_id
            and _item_is_stackable(self.hand_item)
            and slot.quantity < MAX_STACK_PER_ITEM
        ):
            space = MAX_STACK_PER_ITEM - slot.quantity
            move = min(self.hand_qty, space)
            slot.quantity += move
            self.hand_qty -= move
            if self.hand_qty <= 0:
                self.hand_item = None
                self.hand_qty = 0
            _clear_slot_visual(slot)
            self.sync_belt_from_waist()
            return

        old_it, old_q = slot.item, slot.quantity
        slot.item, slot.quantity = self.hand_item, self.hand_qty
        self.hand_item, self.hand_qty = old_it, old_q
        _clear_slot_visual(slot)
        self.sync_belt_from_waist()

    def use_selected_backpack_item(self):
        """Consume one charge from selected backpack slot if it is a consumable."""
        slot = self.slots[self.backpack_start_index + self.selected_backpack_index]
        if slot.item is None or slot.quantity <= 0:
            return
        if getattr(slot.item, "effect_type", None) != "consumable":
            return
        self.player.apply_item_effect(slot.item.effect)
        slot.quantity -= 1
        if slot.quantity <= 0:
            slot.item = None
            slot.quantity = 0
            _clear_slot_visual(slot)

    def use_belt_slot(self, index):
        if not getattr(self.player, "has_belt", False):
            return
        if index < 0 or index >= getattr(self.player, "belt_capacity", 0):
            return
        slot = self.slots[self.belt_start_index + index]
        if slot.item is None or slot.quantity <= 0:
            return
        if getattr(slot.item, "effect_type", None) != "consumable":
            return
        if not _can_place_on_belt(slot.item):
            return
        self.player.apply_item_effect(slot.item.effect)
        slot.quantity -= 1
        if slot.quantity <= 0:
            slot.item = None
            slot.quantity = 0
            _clear_slot_visual(slot)

    def return_hand_to_backpack(self):
        """When closing inventory, move lifted stack back into backpack if possible."""
        if self.hand_item is None or self.hand_qty <= 0:
            return
        target = self.hand_qty
        moved = 0
        for _ in range(target):
            if not self.add_item(self.hand_item):
                break
            moved += 1
        self.hand_qty -= moved
        if self.hand_qty <= 0:
            self.hand_item = None
            self.hand_qty = 0

    def add_item(self, item):
        backpack = self.slots[self.backpack_start_index : self.belt_start_index]

        if _item_is_stackable(item):
            for slot in backpack:
                if (
                    slot.item is not None
                    and slot.item.item_id == item.item_id
                    and slot.quantity < MAX_STACK_PER_ITEM
                ):
                    slot.quantity += 1
                    _player_item_log.debug("stacked item:%s qty=%s", item.item_id, slot.quantity)
                    return True

        for slot in backpack:
            if slot.item is None:
                slot.item = item
                slot.quantity = 1
                _player_item_log.debug("item assigned:%s", item)
                return True

        _player_item_log.debug("Inventory is full.")
        return False
