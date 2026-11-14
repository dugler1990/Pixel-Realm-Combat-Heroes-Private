"""The inventory window: where the slots sit, how they are drawn, and the one cursor that moves over them.

The model (Inventory.py) holds the items; this reads it and calls its changes (lift, place, put_on, use).

Keys: arrows (d-pad) move to the nearest slot in that direction, over the doll, the pack and the belt. Enter
lifts / places; on armour in the pack with nothing in hand, it puts it on. U uses a pack item. Tab jumps to
the next area. While an item is held, the body and belt slots it fits glow and the others fade.

The item card (right of the pack) shows the item under the cursor, or the held one over an empty slot
(item_card.py says what; CardPanel draws it). Hold Shift: every property as a number.
"""
import pygame

import equipment
import item_card
import legion_ui as L
from ImageCache import ImageCache
from Inventory import BACKPACK_COLS, BACKPACK_ROWS, BELT_SLOT_COUNT, BODY, PACK, BELT

ARROWS = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}
DOLL_ASPECT = 678 / 1384           # doll.png width / height
DETAIL_KEYS = (pygame.K_LSHIFT, pygame.K_RSHIFT)
CARD_SHARE = 0.42                  # the item card's share of the width right of the doll (the pack has the rest)
CARD_MIN_W = 150                   # preview px; narrower (trade's half window): no card
CARD_STYLE = {                     # card row kind: (font role, size, colour)
    "name": ("display", 20, L.GOLD), "type": ("body", 12, L.MUTED), "verdict": ("body", 13, L.TEXT),
    "line": ("body", 13, L.TEXT), "flavour": ("body", 12, L.MUTED), "label": ("body", 12, L.MUTED),
    "value": ("medium", 12, L.TEXT), "hint": ("body", 12, L.MUTED),
}


def neighbour(centres, cur, dx, dy):
    """The slot to move to from `cur` going (dx, dy): of the slots ahead (within about 63 degrees of the
    direction), the nearest, counting sideways distance double. `centres`: {index: (x, y)}. None at an edge."""
    cx, cy = centres[cur]
    best, best_score = None, None
    for i, (x, y) in centres.items():
        if i == cur:
            continue
        along = (x - cx) * dx + (y - cy) * dy
        across = abs((x - cx) * dy - (y - cy) * dx)
        if along <= 0 or across > 2 * along:
            continue
        score = along + 2 * across
        if best_score is None or score < best_score:
            best, best_score = i, score
    return best


def wrap(font, text, width):
    """Text broken at word breaks to fit `width` px: a list of lines."""
    rows, current = [], ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if current and font.size(trial)[0] > width:
            rows.append(current)
            current = word
        else:
            current = trial
    return rows + [current] if current else rows


class CardPanel:
    """The card for the item under the cursor (item_card.build). Its rows are made once, when the item, its
    durability, the detail key or the size changes; each row draws through its own TextSlot, which renders only
    when its text changes. Nothing is rebuilt per frame."""

    def __init__(self):
        self._key = None
        self._rows = []          # (style, text, align "left" | "right", y from the top of the text area)
        self._slots = {}         # (row index, style) -> TextSlot

    def _make_rows(self, kit, item, width, detail):
        card = item_card.build(item)
        rows, y = [], 0

        def add(style, text, gap=0):
            nonlocal y
            role, size, _ = CARD_STYLE[style]
            font = kit.font(role, size)
            y += gap
            for line in wrap(font, text, width):
                rows.append((style, line, "left", y))
                y += font.get_linesize()

        def rule():
            nonlocal y
            y += kit.px(6)
            rows.append(("rule", "", "left", y))
            y += kit.px(8)

        add("name", card.name)
        if card.type_line:
            add("type", card.type_line, kit.px(2))
        if card.verdicts:                       # from the rule function (next chunk); empty until then
            rule()
            for text in card.verdicts:
                add("verdict", text)
        if detail and card.detail:
            rule()
            line_h = kit.font(*CARD_STYLE["value"][:2]).get_linesize()
            for label, value in card.detail:
                rows.append(("label", label, "left", y))
                rows.append(("value", value, "right", y))
                y += line_h
        elif card.lines:
            rule()
            for text in card.lines:
                add("line", text)
        if card.flavour:
            add("flavour", card.flavour, kit.px(10))
        if card.detail and not detail:
            add("hint", "Hold Shift: every number", kit.px(10))
        return rows

    def draw(self, backend, kit, rect, item, detail):
        L.draw(backend, kit.plaque(rect.w, rect.h), rect.topleft)
        if item is None:
            return
        pad = kit.px(18)
        width = rect.w - 2 * pad
        key = (item, item_card.state(item), detail, width, kit.size)
        if key != self._key:
            if self._key is None or self._key[-1] != kit.size:
                self._slots = {}                # TextSlots hold a font size: new ones for a new window size
            self._rows = self._make_rows(kit, item, width, detail)
            self._key = key
        x, top = rect.x + pad, rect.y + pad
        for i, (style, text, align, y) in enumerate(self._rows):
            if top + y > rect.bottom - pad:
                break
            if style == "rule":
                L.draw(backend, kit.rule(width), (x, top + y))
                continue
            slot = self._slots.get((i, style))
            if slot is None:
                role, size, colour = CARD_STYLE[style]
                slot = self._slots[(i, style)] = L.TextSlot(backend, kit, role, size, colour)
            if align == "right":
                slot.draw(text, (x + width, top + y), "topright")
            else:
                slot.draw(text, (x, top + y))


class InventoryView:
    def __init__(self, inventory):
        self.inv = inventory
        self.cursor = inventory.backpack_start_index        # index into inventory.slots
        self._gold = None                                   # the gold count's TextSlot, made on first draw
        self.card = CardPanel()
        self.detail = False                                 # Shift held: the card shows every number

    # --- which slots the cursor may visit ----------------------------------------------------------------

    def reachable(self, index):
        inv = self.inv
        if inv.area(index) != BELT:
            return True
        return getattr(inv.player, "has_belt", False) and not inv.belt_locked(index - inv.belt_start_index)

    def _check_cursor(self):
        if not self.reachable(self.cursor):
            self.cursor = self.inv.backpack_start_index

    def move(self, dx, dy):
        centres = {i: s.rect.center for i, s in enumerate(self.inv.slots) if self.reachable(i)}
        nxt = neighbour(centres, self.cursor, dx, dy)
        if nxt is not None:
            self.cursor = nxt

    def next_area(self):
        inv = self.inv
        starts = [inv.body_start_index, inv.backpack_start_index, inv.belt_start_index]
        order = [BODY, PACK, BELT]
        k = order.index(inv.area(self.cursor))
        for step in (1, 2, 3):
            start = starts[(k + step) % 3]
            if self.reachable(start):
                self.cursor = start
                return

    # --- layout and drawing ------------------------------------------------------------------------------

    def layout(self, kit, placed=None):
        """Place every slot for this window: the slab, the doll and its slots, the pack and the belt.
        `placed` is a rect when another screen, such as trade, sits this window on one side."""
        inv = self.inv
        if placed is None:
            width = min(kit.width - kit.px(56), round((kit.height - kit.px(40)) * 1.25))
            slab = pygame.Rect(0, 0, width, round(width * 0.8))
            slab.center = (kit.width // 2, kit.height // 2)
        else:
            slab = pygame.Rect(placed)
            width = slab.w
        inner = slab.inflate(-round(width * 0.12), -round(width * 0.10))
        top = inner.y + kit.font("display", 32).get_height() + kit.px(10)
        cell, gap = kit.px(46), kit.px(6)
        belt_h = cell + kit.px(14)
        doll_h = inner.bottom - top - belt_h
        doll = pygame.Rect(inner.x, top, round(doll_h * DOLL_ASPECT), doll_h)
        for slot, b in zip(inv.body_slots(), equipment.BODY):
            fx, fy, fw, fh = b.doll
            slot.rect = pygame.Rect(doll.x + round(doll.w * fx), doll.y + round(doll.h * fy),
                                    round(doll.w * fw), round(doll.h * fh))
        belt_w = BELT_SLOT_COUNT * cell + (BELT_SLOT_COUNT - 1) * gap
        bx = doll.centerx - belt_w // 2
        for i, slot in enumerate(inv.belt_slots()):
            slot.rect = pygame.Rect(bx + i * (cell + gap), inner.bottom - cell, cell, cell)
        pack_x = doll.right + kit.px(40)
        label_h = kit.font("body", 12).get_height() + kit.px(8)
        room = inner.right - pack_x
        card_w = round(room * CARD_SHARE)
        if card_w < kit.px(CARD_MIN_W):             # too narrow (trade's half window): no card
            card_w = 0
        pack_w = room - card_w - (kit.px(24) if card_w else 0)
        row_h = (inner.bottom - top - label_h - (BACKPACK_ROWS - 1) * kit.px(10)) // BACKPACK_ROWS
        side = min((pack_w - (BACKPACK_COLS - 1) * kit.px(10)) // BACKPACK_COLS, row_h)
        for i, slot in enumerate(inv.pack_slots()):         # rows fill the height, so they face the doll's rows
            r, c = divmod(i, BACKPACK_COLS)
            cy = top + label_h + r * (row_h + kit.px(10)) + row_h // 2
            slot.rect = pygame.Rect(pack_x + c * (side + kit.px(10)), cy - side // 2, side, side)
        card = pygame.Rect(inner.right - card_w, top, card_w, inner.bottom - top) if card_w else None
        return slab, inner, doll, (pack_x, top), card

    def draw(self, backend, placed=None, show_highlight=True):
        """The window in the Legion look. Trade draws it while `visible` is false, on `placed`, and can hide
        the cursor."""
        inv = self.inv
        if not inv.visible and placed is None:
            return
        self._check_cursor()
        kit = L.kit_for(backend)
        slab, inner, doll, (pack_x, pack_y), card = self.layout(kit, placed)
        L.draw(backend, kit.picture("slab.png", width=slab.w), slab.topleft)
        L.draw(backend, kit.label("Inventory", "display", 32, L.GOLD), inner.topleft)
        if self._gold is None:
            self._gold = L.TextSlot(backend, kit, "body", 16, L.GOLD, spacing=0.12)
        self._gold.draw(f"{getattr(inv.player, 'gold', 0)} gold", (inner.right, inner.y + kit.px(8)), "topright")
        L.draw(backend, kit.picture("doll.png", height=doll.h), doll.topleft)
        L.draw(backend, kit.label("Pack", "body", 12, L.GOLD, spacing=0.14, upper=True), (pack_x, pack_y))
        held = inv.hand_item if inv.hand_qty > 0 else None
        for i, slot in enumerate(inv.slots):
            r = slot.rect
            area = inv.area(i)
            if show_highlight and i == self.cursor:
                edge, glow = kit.highlight(r.w, r.h)
                L.draw(backend, edge, (r.x - glow, r.y - glow))
            L.draw(backend, kit.socket(r.w, r.h) if area == BODY else kit.slot(r.w, r.h), r.topleft)
            picture = slot.picture(kit, round(r.w * 0.78), round(r.h * 0.78))
            if picture is not None:
                L.draw(backend, picture, (r.centerx - picture.get_width() // 2, r.centery - picture.get_height() // 2))
                if slot.quantity > 1:
                    count = kit.label(str(slot.quantity), "medium", 12, L.TEXT)
                    L.draw(backend, count, (r.right - count.get_width() - kit.px(4), r.bottom - count.get_height()))
            elif slot.kind == "helmet":
                sigil = kit.faint("sigil.png", round(r.h * 0.72))
                L.draw(backend, sigil, (r.centerx - sigil.get_width() // 2, r.centery - round(r.h * 0.36)))
            if area == BELT and inv.belt_locked(i - inv.belt_start_index):
                L.draw(backend, kit.dimmer(r.w, r.h), r.topleft)
            elif held is not None and area != PACK:        # where the held item goes
                L.draw(backend, kit.fit_glow(r.w, r.h) if inv.can_place(slot, held) else kit.faded(r.w, r.h),
                       r.topleft)
        if card is not None:
            self.card.draw(backend, kit, card, inv.slots[self.cursor].item or held, self.detail)
        self._draw_hand(backend, kit)

    def _draw_hand(self, backend, kit):
        """The item being moved, beside the cursor's slot."""
        inv = self.inv
        if inv.hand_item is None or inv.hand_qty <= 0:
            return
        path = getattr(inv.hand_item, "image_path", None)
        if not path:
            return
        side = kit.px(40)
        picture = kit.fitted(ImageCache.load_image(path), side, side, path)
        cx, cy = inv.slots[self.cursor].rect.center
        L.draw(backend, picture, (cx + kit.px(24), cy - kit.px(8)))
        if inv.hand_qty > 1:
            L.draw(backend, kit.label(str(inv.hand_qty), "medium", 13, L.GOLD), (cx + kit.px(24) + side, cy + kit.px(8)))

    # --- keys --------------------------------------------------------------------------------------------

    def input(self):
        inv = self.inv
        keys = inv.input_manager
        player = inv.player
        level = getattr(player, "level", None)
        trade = getattr(getattr(level, "dialogue", None), "trade", None)
        if trade is not None and getattr(trade, "visible", False):
            return
        now = pygame.time.get_ticks()
        if keys.is_key_just_pressed(pygame.K_i):
            if now - player.last_i_press_time > 500:
                player.level.toggle_inventory()
                player.last_i_press_time = now
            return
        if not inv.visible:
            return
        self.detail = any(keys.is_key_pressed(k) for k in DETAIL_KEYS)
        self._check_cursor()
        if keys.is_key_just_pressed(pygame.K_TAB):
            self.next_area()
            return
        for key, (dx, dy) in ARROWS.items():
            if keys.is_key_just_pressed(key):
                self.move(dx, dy)
                return
        slot = inv.slots[self.cursor]
        if keys.is_key_just_pressed(pygame.K_u):
            if inv.area(self.cursor) == PACK:
                inv.use(slot)
            return
        if keys.is_key_just_pressed(pygame.K_RETURN):
            if inv.hand_item is not None:
                inv.place(slot)
            elif inv.area(self.cursor) == PACK and equipment.wearable(slot.item):
                inv.put_on(slot)
            else:
                inv.lift(slot)
