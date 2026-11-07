import pygame
from ImageCache import ImageCache
import legion_ui as L
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

def _item_is_stackable(item):
    return getattr(item, "effect_type", None) == "consumable"


def _can_place_on_belt(item):
    return (
        getattr(item, "belt_allowed", False)
        and getattr(item, "effect_type", None) == "consumable"
    )


class InventorySlot:
    def __init__(self, rect, slot_type="general", angle=0):
        self.rect = rect
        self.slot_type = slot_type
        self.angle = angle
        self.item = None
        self.quantity = 0

    def picture(self, kit, w, h):
        """The item's picture fitted inside w x h, kept; None when the slot is empty."""
        path = getattr(self.item, "image_path", None) if self.item is not None else None
        if not path:
            return None
        return kit.fitted(ImageCache.load_image(path), w, h, path)


def draw_belt_hud(backend, player, inventory):
    """Bottom-centre belt during gameplay: four slot frames with their numbers above, the item
    and its count in each, locked slots greyed. Every piece is kept, so a frame makes none."""
    if not getattr(player, "has_belt", False):
        return
    cap = getattr(player, "belt_capacity", 0)
    if cap <= 0:
        return
    kit = L.kit_for(backend)
    side, gap = kit.px(48), kit.px(10)
    total_w = BELT_SLOT_COUNT * side + (BELT_SLOT_COUNT - 1) * gap
    W, H = backend.get_size()
    x0 = (W - total_w) // 2
    y0 = H - side - kit.px(18)
    for i in range(BELT_SLOT_COUNT):
        r = pygame.Rect(x0 + i * (side + gap), y0, side, side)
        src = inventory.slots[inventory.belt_start_index + i]
        L.draw(backend, kit.slot(side, side), r.topleft)
        if i >= cap:
            L.draw(backend, kit.dimmer(side, side), r.topleft)
        elif src.item is not None and src.quantity > 0:
            picture = src.picture(kit, round(side * 0.78), round(side * 0.78))
            if picture is not None:
                L.draw(backend, picture, (r.centerx - picture.get_width() // 2, r.centery - picture.get_height() // 2))
            if src.quantity > 1:
                count = kit.label(str(int(src.quantity)), "medium", 12, L.TEXT)
                L.draw(backend, count, (r.right - count.get_width() - kit.px(3), r.bottom - count.get_height()))
        number = kit.label(str(i + 1), "body", 12, L.MUTED)
        L.draw(backend, number, (r.centerx - number.get_width() // 2, r.y - number.get_height()))


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

        self._gold = None  # the gold count's TextSlot, made on first display

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

    DOLL_SLOTS = (
        (0.37, 0.02, 0.26, 0.15),  # helmet
        (0.35, 0.21, 0.30, 0.17),  # armour
        (0.00, 0.47, 0.15, 0.09),  # arm, left
        (0.85, 0.47, 0.15, 0.09),  # arm, right
        (0.03, 0.58, 0.14, 0.19),  # weapon, left
        (0.83, 0.58, 0.14, 0.19),  # weapon, right
        (0.22, 0.90, 0.23, 0.09),  # boots, left
        (0.58, 0.90, 0.23, 0.09),  # boots, right
        (0.35, 0.395, 0.30, 0.065),  # waist
    )

    def _layout(self, kit):
        """Place every slot for this window: the slab, the doll and its slots, the pack and the
        belt. The slots' rects are set here, so the held item follows the focused slot."""
        width = min(kit.width - kit.px(56), round((kit.height - kit.px(40)) * 1.25))
        slab = pygame.Rect(0, 0, width, round(width * 0.8))
        slab.center = (kit.width // 2, kit.height // 2)
        inner = slab.inflate(-round(width * 0.12), -round(width * 0.10))
        top = inner.y + kit.font("display", 32).get_height() + kit.px(10)
        cell, gap = kit.px(46), kit.px(6)
        belt_h = cell + kit.px(14)
        doll_h = inner.bottom - top - belt_h
        doll = pygame.Rect(inner.x, top, round(doll_h * 678 / 1384), doll_h)
        for i, (fx, fy, fw, fh) in enumerate(self.DOLL_SLOTS):
            self.slots[self.body_start_index + i].rect = pygame.Rect(
                doll.x + round(doll.w * fx), doll.y + round(doll.h * fy), round(doll.w * fw), round(doll.h * fh))
        belt_w = BELT_SLOT_COUNT * cell + (BELT_SLOT_COUNT - 1) * gap
        bx = doll.centerx - belt_w // 2
        for i in range(BELT_SLOT_COUNT):
            self.slots[self.belt_start_index + i].rect = pygame.Rect(bx + i * (cell + gap), inner.bottom - cell, cell, cell)
        pack_x = doll.right + kit.px(40)
        label_h = kit.font("body", 12).get_height() + kit.px(8)
        side = min((inner.right - pack_x - (BACKPACK_COLS - 1) * kit.px(10)) // BACKPACK_COLS,
                   (inner.bottom - top - label_h - (BACKPACK_ROWS - 1) * kit.px(10)) // BACKPACK_ROWS)
        for r in range(BACKPACK_ROWS):
            for c in range(BACKPACK_COLS):
                self.slots[self.backpack_start_index + r * BACKPACK_COLS + c].rect = pygame.Rect(
                    pack_x + c * (side + kit.px(10)), top + label_h + r * (side + kit.px(10)), side, side)
        return slab, inner, doll, (pack_x, top)

    def _selected(self, i):
        if i < self.backpack_start_index:
            return self.focus_region == FOCUS_BODY and i - self.body_start_index == self.body_index
        if i < self.belt_start_index:
            return self.focus_region == FOCUS_BACKPACK and i - self.backpack_start_index == self.selected_backpack_index
        return self.focus_region == FOCUS_BELT and i - self.belt_start_index == self.belt_index

    def display(self, backend):
        """The inventory in the Legion look: the stone slab at its own 5:4, the painted figure
        with its body slots on it, the pack 3 wide and 4 tall, the belt of four under the figure."""
        if not self.visible:
            return
        kit = L.kit_for(backend)
        slab, inner, doll, (pack_x, pack_y) = self._layout(kit)
        L.draw(backend, kit.picture("slab.png", width=slab.w), slab.topleft)
        L.draw(backend, kit.label("Inventory", "display", 32, L.GOLD), inner.topleft)
        if self._gold is None:
            self._gold = L.TextSlot(backend, kit, "body", 16, L.GOLD, spacing=0.12)
        self._gold.draw(f"{getattr(self.player, 'gold', 0)} gold", (inner.right, inner.y + kit.px(8)), "topright")
        L.draw(backend, kit.picture("doll.png", height=doll.h), doll.topleft)
        L.draw(backend, kit.label("Pack", "body", 12, L.GOLD, spacing=0.14, upper=True), (pack_x, pack_y))
        for i, slot in enumerate(self.slots):
            r = slot.rect
            if self._selected(i):
                edge, glow = kit.highlight(r.w, r.h)
                L.draw(backend, edge, (r.x - glow, r.y - glow))
            body = i < self.backpack_start_index
            L.draw(backend, kit.socket(r.w, r.h) if body else kit.slot(r.w, r.h), r.topleft)
            picture = slot.picture(kit, round(r.w * 0.78), round(r.h * 0.78))
            if picture is not None:
                L.draw(backend, picture, (r.centerx - picture.get_width() // 2, r.centery - picture.get_height() // 2))
                if slot.quantity > 1:
                    count = kit.label(str(slot.quantity), "medium", 12, L.TEXT)
                    L.draw(backend, count, (r.right - count.get_width() - kit.px(4), r.bottom - count.get_height()))
            elif slot.slot_type == "helmet":
                L.draw(backend, kit.faint("sigil.png", round(r.h * 0.72)), (r.centerx - kit.faint("sigil.png", round(r.h * 0.72)).get_width() // 2,
                                                                          r.centery - round(r.h * 0.36)))
            if slot.slot_type == "belt" and self._belt_slot_locked(i - self.belt_start_index):
                L.draw(backend, kit.dimmer(r.w, r.h), r.topleft)
        self._draw_hand(backend, kit)

    def _draw_hand(self, backend, kit):
        """The item being moved, beside the focused slot."""
        if self.hand_item is None or self.hand_qty <= 0:
            return
        path = getattr(self.hand_item, "image_path", None)
        if not path:
            return
        side = kit.px(40)
        picture = kit.fitted(ImageCache.load_image(path), side, side, path)
        cx, cy = self._get_focused_slot().rect.center
        L.draw(backend, picture, (cx + kit.px(24), cy - kit.px(8)))
        if self.hand_qty > 1:
            L.draw(backend, kit.label(str(self.hand_qty), "medium", 13, L.GOLD), (cx + kit.px(24) + side, cy + kit.px(8)))

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
            self.sync_belt_from_waist()
            return

        old_it, old_q = slot.item, slot.quantity
        slot.item, slot.quantity = self.hand_item, self.hand_qty
        self.hand_item, self.hand_qty = old_it, old_q
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

    def has_room_for(self, item):
        """Non-mutating: would add_item() succeed? (room in an existing stack or
        an empty backpack slot). Used by co-op to pre-check before requesting a
        shared pickup, so the host doesn't award an item we can't hold."""
        backpack = self.slots[self.backpack_start_index : self.belt_start_index]
        if _item_is_stackable(item):
            for slot in backpack:
                if (slot.item is not None and slot.item.item_id == item.item_id
                        and slot.quantity < MAX_STACK_PER_ITEM):
                    return True
        return any(slot.item is None for slot in backpack)

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
