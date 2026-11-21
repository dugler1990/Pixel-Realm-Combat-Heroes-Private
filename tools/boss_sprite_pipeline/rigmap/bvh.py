"""BVH hierarchy only. Offsets are centimetres, parent-local, identity rest rotation."""
from __future__ import annotations

class Skeleton:
    def __init__(self):
        self.names: list[str] = []
        self.parent: dict[str, str | None] = {}
        self.offset: dict[str, tuple[float, float, float]] = {}
        self.world: dict[str, tuple[float, float, float]] = {}

    def direction(self, name: str):
        """Unit vector toward the first child, or None at a tip."""
        kids = [n for n, p in self.parent.items() if p == name]
        if not kids:
            return None
        ax, ay, az = self.world[name]
        bx, by, bz = self.world[kids[0]]
        v = (bx - ax, by - ay, bz - az)
        n = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
        if n < 1e-8:
            return None
        return (v[0] / n, v[1] / n, v[2] / n)


def load_bvh(text: str) -> Skeleton:
    sk = Skeleton()
    stack: list[str | None] = []
    pending: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("MOTION"):
            break
        if line.startswith("ROOT") or line.startswith("JOINT"):
            pending = line.split()[1]
            continue
        if line.startswith("End Site"):
            pending = None
            continue
        if line == "{":
            stack.append(pending)
            pending = None
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        if line.startswith("OFFSET") and stack and stack[-1]:
            name = stack[-1]
            if name in sk.offset:
                continue
            _, xs, ys, zs = line.split()[:4]
            off = (float(xs), float(ys), float(zs))
            parent = stack[-2] if len(stack) > 1 else None
            sk.names.append(name)
            sk.parent[name] = parent
            sk.offset[name] = off
            if parent is None:
                sk.world[name] = off
            else:
                px, py, pz = sk.world[parent]
                sk.world[name] = (px + off[0], py + off[1], pz + off[2])
    if not sk.names:
        raise ValueError("no joints in bvh")
    return sk
