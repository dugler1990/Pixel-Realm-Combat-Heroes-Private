"""The trader's icon grid beside the player's own inventory window.

His side is the inventory's slot grid without the body: one icon per ware, category
tabs along the top. The right side is Inventory.display, the same slab, doll, pack and belt.
"""

import json
from pathlib import Path

import pygame

import legion_ui as L
from ImageCache import ImageCache
from Inventory import BACKPACK_COLS
from Item import Item

_CODE = Path(__file__).resolve().parents[1]
_ITEMS = _CODE.parent / "Graphics" / "Standard_Items" / "standard_items.json"
_definitions = None
_resolved = {}

TABS = (("all", "All"), ("goods", "Goods"), ("gear", "Gear"), ("other", "Other"))
_GEAR = {"equipable", "weapon", "belt"}
_REFUSED = {"key", "gold"}
SHOP_COLS = 4
SHOP_ROWS = 4


def item_definitions():
    global _definitions
    if _definitions is None:
        _definitions = {}
        if _ITEMS.is_file():
            for row in json.loads(_ITEMS.read_text(encoding="utf-8")):
                if isinstance(row, dict) and row.get("item_id"):
                    _definitions[row["item_id"]] = row
    return _definitions


def resolve_image(raw):
    if not raw:
        return None
    if raw in _resolved:
        return _resolved[raw]
    found = None
    direct = Path(raw)
    if direct.is_file():
        found = str(direct.resolve())
    else:
        sibling = (_CODE / raw).resolve()
        if sibling.is_file():
            found = str(sibling)
    _resolved[raw] = found
    return found


def category_of(item_id):
    kind = (item_definitions().get(item_id) or {}).get("item_type") or ""
    if kind == "consumable":
        return "goods"
    if kind in _GEAR:
        return "gear"
    return "other"


def make_item(item_id):
    row = item_definitions().get(item_id)
    if row is None:
        return None
    return Item(
        row.get("image_path") or "",
        (0, 0),
        item_id,
        effect=row.get("effect"),
        effect_type=row.get("effect_type") or "",
        item_type=row.get("item_type") or "",
        belt_allowed=bool(row.get("belt_allowed", False)),
        base=row.get("base"),
        name=row.get("name"),
        description=row.get("description", ""),
    )


class TradeWindow:
    def __init__(self):
        self.visible = False
        self.shop_id = ""
        self.title = ""
        self.goods = []
        self.side = 0
        self.shop_tab = 0
        self.shop_index = 0
        self.pack_index = 0
        self.notice = ""
        self._player = None
        self._gold = None
        self._caption = None

    def open(self, shop_id, shop, player):
        if not isinstance(shop, dict) or player is None:
            return False
        goods = [row for row in shop.get("goods") or [] if isinstance(row, dict) and row.get("item_id")]
        if not goods:
            return False
        self.visible = True
        self.shop_id = shop_id
        self.title = shop.get("name") or shop_id
        self.goods = goods
        self.side = 0
        self.shop_tab = 0
        self.shop_index = 0
        self.pack_index = 0
        self.notice = ""
        self._player = player
        return True

    def close(self):
        self.visible = False
        self._player = None

    def handle_input(self, input_manager):
        if not self.visible:
            return False
        if input_manager.is_key_just_pressed(pygame.K_ESCAPE):
            self.close()
            return True
        if input_manager.is_key_just_pressed(pygame.K_TAB):
            self.side = 0 if self.side == 1 else 1
            self._sync_cursor()
        elif input_manager.is_key_just_pressed(pygame.K_e):
            self._cycle_tab(1)
        elif input_manager.is_key_just_pressed(pygame.K_q):
            self._cycle_tab(-1)
        elif input_manager.is_key_just_pressed(pygame.K_LEFT):
            self._move(-1, 0)
        elif input_manager.is_key_just_pressed(pygame.K_RIGHT):
            self._move(1, 0)
        elif input_manager.is_key_just_pressed(pygame.K_UP):
            self._move(0, -1)
        elif input_manager.is_key_just_pressed(pygame.K_DOWN):
            self._move(0, 1)
        elif input_manager.is_key_just_pressed(pygame.K_RETURN) or input_manager.is_key_just_pressed(pygame.K_SPACE):
            if self.side == 0:
                self.buy()
            else:
                self.sell()
        return True

    def buy(self):
        player = self._player
        rows = self._shop_rows()
        if player is None or self.shop_index >= len(rows):
            self.notice = "Nothing here"
            return False
        good = rows[self.shop_index]
        price = int(good.get("price") or 0)
        name = good.get("name") or _pretty(good["item_id"])
        if int(getattr(player, "gold", 0)) < price:
            self.notice = "Not enough gold"
            return False
        item = make_item(good["item_id"])
        if item is None:
            self.notice = "Not for sale"
            return False
        inventory = getattr(player, "inventory", None)
        if inventory is None or not inventory.add_item(item):
            self.notice = "Pack is full"
            return False
        player.gold = int(player.gold) - price
        self.notice = f"Bought {name}"
        return True

    def sell(self):
        player = self._player
        slots = self._pack_slots()
        if player is None or self.pack_index >= len(slots):
            self.notice = "Nothing to sell"
            return False
        slot = slots[self.pack_index]
        item = getattr(slot, "item", None)
        if item is None or int(getattr(slot, "quantity", 0) or 0) <= 0:
            self.notice = "Nothing to sell"
            return False
        item_id = getattr(item, "item_id", "")
        kind = getattr(item, "effect_type", None) or getattr(item, "item_type", None)
        if kind in _REFUSED:
            self.notice = "He won't buy that"
            return False
        price = self._sell_price(item_id)
        slot.quantity = int(slot.quantity) - 1
        if slot.quantity <= 0:
            slot.item = None
            slot.quantity = 0
        player.gold = int(getattr(player, "gold", 0)) + price
        self.notice = f"Sold {_pretty_known(self.goods, item_id)} for {price}"
        return True

    def draw(self, backend):
        if not self.visible:
            return
        kit = L.kit_for(backend)
        L.draw(backend, kit.shade("dim"), (0, 0))
        left, right = _panels(kit)
        self._draw_shop(backend, kit, left)
        self._sync_cursor()
        inventory = getattr(self._player, "inventory", None)
        if inventory is not None and hasattr(inventory, "display"):
            inventory.display(backend, placed=right, show_highlight=self.side == 1)

    def _shop_rows(self):
        tab = TABS[self.shop_tab][0]
        return [good for good in self.goods if tab == "all" or category_of(good["item_id"]) == tab]

    def _pack_slots(self):
        inventory = getattr(self._player, "inventory", None)
        slots = list(getattr(inventory, "slots", None) or [])
        start = int(getattr(inventory, "backpack_start_index", 0) or 0)
        end = getattr(inventory, "belt_start_index", None)
        if end is None:
            return slots[start:]
        return slots[start:int(end)]

    def _sell_price(self, item_id):
        for good in self.goods:
            if good.get("item_id") == item_id:
                if good.get("sell") is not None:
                    return max(0, int(good["sell"]))
                return max(1, int(good.get("price") or 0) // 2)
        return 1

    def _cycle_tab(self, delta):
        if self.side != 0:
            return
        self.notice = ""
        self.shop_tab = (self.shop_tab + delta) % len(TABS)
        self.shop_index = 0

    def _move(self, dx, dy):
        self.notice = ""
        if self.side == 0:
            self._move_shop(dx, dy)
        else:
            self._move_pack(dx, dy)

    def _move_shop(self, dx, dy):
        col, row = self.shop_index % SHOP_COLS, self.shop_index // SHOP_COLS
        if dx > 0 and col == SHOP_COLS - 1:
            self.side = 1
            self.pack_index = 0
            self._sync_cursor()
            return
        ncol = max(0, min(SHOP_COLS - 1, col + dx))
        nrow = max(0, min(SHOP_ROWS - 1, row + dy))
        self.shop_index = nrow * SHOP_COLS + ncol

    def _move_pack(self, dx, dy):
        count = len(self._pack_slots())
        if count <= 0:
            if dx < 0:
                self.side = 0
            return
        cols = BACKPACK_COLS
        index = min(self.pack_index, count - 1)
        col, row = index % cols, index // cols
        if dx < 0 and col == 0:
            self.side = 0
            return
        nxt = (row + dy) * cols + (col + dx)
        ncol = col + dx
        if ncol < 0 or ncol >= cols or nxt < 0 or nxt >= count:
            return
        self.pack_index = nxt
        self._sync_cursor()

    def _sync_cursor(self):
        """The inventory window's cursor on the pack slot chosen here (it is drawn only on the pack side)."""
        inventory = getattr(self._player, "inventory", None)
        view = getattr(inventory, "view", None)
        slots = self._pack_slots()
        if view is not None and slots:
            view.cursor = inventory.backpack_start_index + min(self.pack_index, len(slots) - 1)

    def _draw_shop(self, backend, kit, slab):
        L.draw(backend, kit.picture("slab.png", width=slab.w), slab.topleft)
        inner = slab.inflate(-round(slab.w * 0.12), -round(slab.w * 0.10))
        title = kit.label(self.title, "display", 28, L.GOLD)
        L.draw(backend, title, inner.topleft)
        gold = self._slot(backend, kit, "_gold").surface(f"{int(getattr(self._player, 'gold', 0))} gold")
        L.draw(backend, gold, (inner.right - gold.get_width(), inner.y + kit.px(6)))
        tx = inner.x
        ty = inner.y + title.get_height() + kit.px(4)
        for i, (_key, name) in enumerate(TABS):
            colour = L.GOLD if i == self.shop_tab else L.MUTED
            label = kit.label(name, "body", 13, colour, spacing=0.08, upper=True)
            L.draw(backend, label, (tx, ty))
            tx += label.get_width() + kit.px(10)
        caption = self._slot(backend, kit, "_caption").surface(self._caption_text())
        cap_y = inner.bottom - caption.get_height()
        grid_top = ty + kit.px(20)
        grid_bottom = cap_y - kit.px(8)
        gap = kit.px(8)
        side = min(
            (inner.w - (SHOP_COLS - 1) * gap) // SHOP_COLS,
            max(1, (grid_bottom - grid_top - (SHOP_ROWS - 1) * gap) // SHOP_ROWS),
        )
        side = max(1, side)
        grid_w = SHOP_COLS * side + (SHOP_COLS - 1) * gap
        gx = inner.x + max(0, (inner.w - grid_w) // 2)
        rows = self._shop_rows()
        for i in range(SHOP_COLS * SHOP_ROWS):
            col, row = i % SHOP_COLS, i // SHOP_COLS
            rect = pygame.Rect(gx + col * (side + gap), grid_top + row * (side + gap), side, side)
            if self.side == 0 and i == self.shop_index:
                edge, glow = kit.highlight(side, side)
                L.draw(backend, edge, (rect.x - glow, rect.y - glow))
            L.draw(backend, kit.slot(side, side), rect.topleft)
            if i >= len(rows):
                continue
            good = rows[i]
            path = (item_definitions().get(good["item_id"]) or {}).get("image_path")
            picture = _picture(kit, path, round(side * 0.78))
            if picture is not None:
                L.draw(backend, picture, (rect.centerx - picture.get_width() // 2, rect.centery - picture.get_height() // 2))
        L.draw(backend, caption, (inner.x, cap_y))

    def _caption_text(self):
        if self.notice:
            return self.notice
        if self.side == 0:
            rows = self._shop_rows()
            if self.shop_index < len(rows):
                good = rows[self.shop_index]
                name = good.get("name") or _pretty(good["item_id"])
                return f"{name}   {int(good.get('price') or 0)} g"
            return " "
        slots = self._pack_slots()
        if self.pack_index >= len(slots):
            return " "
        item = getattr(slots[self.pack_index], "item", None)
        if item is None:
            return " "
        item_id = getattr(item, "item_id", "")
        return f"{_pretty_known(self.goods, item_id)}   sell {self._sell_price(item_id)}"

    def _slot(self, backend, kit, name):
        slot = getattr(self, name)
        if slot is None or slot.backend is not backend:
            size = 16 if name == "_gold" else 14
            slot = L.TextSlot(backend, kit, "medium" if name == "_gold" else "body", size, L.GOLD)
            setattr(self, name, slot)
        return slot


def _panels(kit):
    margin = kit.px(12)
    gap = kit.px(10)
    avail_w = kit.width - 2 * margin - gap
    avail_h = kit.height - 2 * margin
    width = max(kit.px(80), min(avail_w // 2, round(avail_h / 0.8)))
    height = round(width * 0.8)
    x = (kit.width - (width * 2 + gap)) // 2
    y = max(margin, (kit.height - height) // 2)
    return pygame.Rect(x, y, width, height), pygame.Rect(x + width + gap, y, width, height)


def _picture(kit, raw, side):
    path = resolve_image(raw)
    if not path or side <= 0:
        return None
    try:
        image = ImageCache.load_image(path)
    except (pygame.error, FileNotFoundError, OSError):
        return None
    return kit.fitted(image, side, side, path)


def _pretty(item_id):
    return str(item_id).replace("_", " ").title()


def _pretty_known(goods, item_id):
    for good in goods:
        if good.get("item_id") == item_id and good.get("name"):
            return good["name"]
    return _pretty(item_id)
