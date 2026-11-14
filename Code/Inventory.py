"""The hero's items: the body slots (what he wears), the pack, the belt pockets, and the item in hand.

The model only. What fits where: equipment.py. The window, the cursor and the keys: inventory_view.py
(`self.view`; `display` and `input` hand over to it).

Every change to the slots goes through `_changed()`: the belt pockets follow the waist item, and a mesh
hero puts on / takes off what is worn (Player.refresh_equipment -> PlayerMesh.set_pieces).
"""
import pygame

import equipment
import legion_ui as L
from game_logging import get_debug_logger
from ImageCache import ImageCache

_player_item_log = get_debug_logger("player_item")

MAX_STACK_PER_ITEM = 99      # stackable items (consumables) per slot

BODY_SLOTS = tuple(b.kind for b in equipment.BODY)
BODY_SLOT_COUNT = len(equipment.BODY)
BACKPACK_ROWS = 4
BACKPACK_COLS = 3
BACKPACK_COUNT = BACKPACK_ROWS * BACKPACK_COLS
BELT_SLOT_COUNT = 4

BODY, PACK, BELT = "body", "pack", "belt"     # the three areas of the window


def _item_is_stackable(item):
    return getattr(item, "effect_type", None) == "consumable"


class InventorySlot:
    """One slot. `kind`: a body kind (helmet, armor, shoulder, ... waist), "pack" or "belt"; `side`: "l" / "r"
    for paired body slots (the hero's own left / right); `id`: helmet, shoulder_l, ..., pack_0, belt_0."""

    def __init__(self, rect, kind="pack", angle=0, id=None, side=None):
        self.rect = rect
        self.kind = kind
        self.side = side
        self.id = id
        self.angle = angle
        self.item = None
        self.quantity = 0

    @property
    def slot_type(self):        # the old name
        return self.kind

    @property
    def empty(self):
        return self.item is None or self.quantity <= 0

    def clear(self):
        self.item, self.quantity = None, 0

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
        self.player = player
        self.input_manager = input_manager
        self.visible = False
        # Rects are placed by the view each time the window draws.
        self.slots = [InventorySlot(pygame.Rect(0, 0, 50, 50), b.kind, id=b.id, side=b.side) for b in equipment.BODY]
        self.slots += [InventorySlot(pygame.Rect(0, 0, 60, 60), "pack", id=f"pack_{i}") for i in range(BACKPACK_COUNT)]
        self.slots += [InventorySlot(pygame.Rect(0, 0, 44, 44), "belt", id=f"belt_{i}") for i in range(BELT_SLOT_COUNT)]
        self.body_start_index = 0
        self.waist_slot_index = BODY_SLOT_COUNT - 1
        self.backpack_start_index = BODY_SLOT_COUNT
        self.belt_start_index = BODY_SLOT_COUNT + BACKPACK_COUNT
        self.hand_item = None
        self.hand_qty = 0
        from inventory_view import InventoryView
        self.view = InventoryView(self)

    # --- where things are ------------------------------------------------------------------------------------

    def body_slots(self):
        return self.slots[self.body_start_index:self.body_start_index + BODY_SLOT_COUNT]

    def pack_slots(self):
        return self.slots[self.backpack_start_index:self.belt_start_index]

    def belt_slots(self):
        return self.slots[self.belt_start_index:self.belt_start_index + BELT_SLOT_COUNT]

    def slot(self, slot_id):
        return next(s for s in self.slots if s.id == slot_id)

    def area(self, index):
        if index < self.backpack_start_index:
            return BODY
        return PACK if index < self.belt_start_index else BELT

    def belt_locked(self, belt_idx):
        return belt_idx >= getattr(self.player, "belt_capacity", 0)

    def can_place(self, slot, item):
        """The one check before an item goes into a slot: equipment.fits, and an open belt pocket."""
        if slot.kind == "belt" and self.belt_locked(self.slots.index(slot) - self.belt_start_index):
            return False
        return equipment.fits(slot.kind, slot.side, item)

    def worn_pieces(self):
        """The mesh packs of what is worn (helmet ... waist), in slot order."""
        return equipment.worn_pieces(s.item for s in self.body_slots() if not s.empty)

    # --- changes (each ends in _changed) ---------------------------------------------------------------------

    def lift(self, slot):
        """The slot's whole stack into the hand (the hand is empty)."""
        if slot.empty or self.hand_item is not None:
            return False
        if slot.kind == "belt" and self.belt_locked(self.slots.index(slot) - self.belt_start_index):
            return False
        self.hand_item, self.hand_qty = slot.item, slot.quantity
        slot.clear()
        self._changed()
        return True

    def place(self, slot):
        """The hand into the slot: into an empty one, onto the same stack, or swapped with what is there."""
        if self.hand_item is None or self.hand_qty <= 0 or not self.can_place(slot, self.hand_item):
            return False
        if slot.empty:
            slot.item, slot.quantity = self.hand_item, self.hand_qty
            self.hand_item, self.hand_qty = None, 0
        elif (slot.item.item_id == self.hand_item.item_id and _item_is_stackable(self.hand_item)
              and slot.quantity < MAX_STACK_PER_ITEM):
            move = min(self.hand_qty, MAX_STACK_PER_ITEM - slot.quantity)
            slot.quantity += move
            self.hand_qty -= move
            if self.hand_qty <= 0:
                self.hand_item, self.hand_qty = None, 0
        else:
            slot.item, slot.quantity, self.hand_item, self.hand_qty = \
                self.hand_item, self.hand_qty, slot.item, slot.quantity
        self._changed()
        return True

    def body_slot_for(self, item):
        """Where putting `item` on goes: an empty body slot it fits, else a full one (swap). None: not worn."""
        fitting = [s for s in self.body_slots() if equipment.wearable(item) and self.can_place(s, item)]
        return next((s for s in fitting if s.empty), fitting[0] if fitting else None)

    def put_on(self, src):
        """Wear the item in `src` (a pack slot): into its body slot; what was worn there goes to `src`."""
        if src.empty or self.hand_item is not None:
            return False
        dst = self.body_slot_for(src.item)
        if dst is None:
            return False
        dst.item, dst.quantity, src.item, src.quantity = src.item, src.quantity, dst.item, dst.quantity
        self._changed()
        return True

    def wear(self, item):
        """Start gear: put `item` into an empty body slot it fits. False if none."""
        dst = self.body_slot_for(item)
        if dst is None or not dst.empty:
            return False
        dst.item, dst.quantity = item, 1
        self._changed()
        return True

    def use(self, slot):
        """Drink / eat one from a pack slot (consumables only)."""
        if slot.empty or getattr(slot.item, "effect_type", None) != "consumable":
            return False
        self.player.apply_item_effect(slot.item.effect)
        slot.quantity -= 1
        if slot.quantity <= 0:
            slot.clear()
        return True

    def use_belt_slot(self, index):
        if not getattr(self.player, "has_belt", False) or self.belt_locked(index) or index < 0:
            return
        slot = self.slots[self.belt_start_index + index]
        if equipment.fits_belt(slot.item):
            self.use(slot)

    def return_hand_to_backpack(self):
        """When closing the window: the held stack back into the pack, as far as it fits."""
        while self.hand_item is not None and self.hand_qty > 0 and self.add_item(self.hand_item):
            self.hand_qty -= 1
        if self.hand_qty <= 0:
            self.hand_item, self.hand_qty = None, 0

    def _changed(self):
        """After every change: the belt pockets the waist item opens (items in pockets that closed go to the
        pack), then what the hero wears."""
        waist = self.slots[self.waist_slot_index]
        worn = None if waist.empty else waist.item
        self.player.has_belt = equipment.wearable(worn) == ("waist", None)
        self.player.belt_capacity = min(BELT_SLOT_COUNT, equipment.belt_pockets(worn))
        for i, pocket in enumerate(self.belt_slots()):
            if i >= self.player.belt_capacity and not pocket.empty:
                while pocket.quantity > 0 and self.add_item(pocket.item):
                    pocket.quantity -= 1
                if pocket.quantity <= 0:
                    pocket.clear()
        refresh = getattr(self.player, "refresh_equipment", None)
        if callable(refresh):
            refresh()

    sync_belt_from_waist = _changed          # the old name (Level4)

    # --- the pack ----------------------------------------------------------------------------------------

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
                if (slot.item is not None and slot.item.item_id == item.item_id
                        and slot.quantity < MAX_STACK_PER_ITEM):
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

    # --- the window (inventory_view.py) ------------------------------------------------------------------

    def toggle_visibility(self):
        self.visible = not self.visible

    def display(self, backend, placed=None, show_highlight=True):
        self.view.draw(backend, placed, show_highlight)

    def input(self):
        self.view.input()
