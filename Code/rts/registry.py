"""Runtime indexes built from map-loaded RTS entities."""


class RtsWorldRegistry:
    def __init__(self):
        self.chiefs = {}
        self.chiefs_by_throne = {}
        self.dropoffs_by_faction = {}
        self.faction_node_index = {}
        self.workers_by_faction = {}
        self.build_sites_by_faction = {}

    def register_chief(self, chief):
        self.chiefs[chief.chief_id] = chief
        throne_id = str(getattr(chief, "throne_id", "")).strip()
        if throne_id:
            self.chiefs_by_throne[throne_id] = chief

    def register_node(self, node):
        fid = str(getattr(node, "faction_id", "")).strip()
        cat = str(getattr(node, "resource_category", "")).strip().lower()
        if not fid or not cat:
            return
        bucket = self.faction_node_index.setdefault(fid, {})
        bucket.setdefault(cat, []).append(node)

    def register_dropoff(self, building):
        fid = str(getattr(building, "faction_id", "")).strip()
        kind = str(getattr(building, "dropoff_kind", "")).strip()
        if not fid or not kind:
            return
        fac = self.dropoffs_by_faction.setdefault(fid, {})
        fac[kind] = building

    def register_worker(self, worker):
        fid = str(getattr(worker, "faction_id", "")).strip()
        self.workers_by_faction.setdefault(fid, []).append(worker)

    def unregister_worker(self, worker):
        fid = str(getattr(worker, "faction_id", "")).strip()
        lst = self.workers_by_faction.get(fid, [])
        if worker in lst:
            lst.remove(worker)

    def get_chief_for_throne(self, throne_profile_id):
        return self.chiefs_by_throne.get(str(throne_profile_id or "").strip())

    def nodes_for_faction(self, faction_id, category=None):
        fac = self.faction_node_index.get(str(faction_id or "").strip(), {})
        if category is not None:
            return list(fac.get(str(category).lower(), []))
        out = []
        for nodes in fac.values():
            out.extend(nodes)
        return out

    def find_dropoff(self, faction_id, dropoff_kind):
        return self.dropoffs_by_faction.get(str(faction_id or "").strip(), {}).get(
            str(dropoff_kind or "").strip()
        )

    def register_build_site(self, site):
        fid = str(getattr(site, "faction_id", "")).strip()
        if not fid:
            return
        self.build_sites_by_faction.setdefault(fid, []).append(site)

    def build_sites_for_faction(self, faction_id, requires=None, available_only=True):
        fid = str(faction_id or "").strip()
        sites = list(self.build_sites_by_faction.get(fid, []))
        if requires is not None:
            req = str(requires).strip()
            sites = [s for s in sites if getattr(s, "requires", "") == req]
        if available_only:
            sites = [s for s in sites if s.is_available()]
        return sites

    def nearest_unbuilt_site(self, faction_id, requires, from_pos):
        sites = self.build_sites_for_faction(faction_id, requires=requires, available_only=True)
        if not sites:
            return None
        fx, fy = from_pos
        return min(
            sites,
            key=lambda s: (s.build_center[0] - fx) ** 2 + (s.build_center[1] - fy) ** 2,
        )

    def nearest_node_with_slot(self, faction_id, category, from_pos):
        nodes = [
            n
            for n in self.nodes_for_faction(faction_id, category)
            if n.is_active() and n.has_free_slot()
        ]
        if not nodes:
            return None
        fx, fy = from_pos
        return min(
            nodes,
            key=lambda n: (n.gather_point[0] - fx) ** 2 + (n.gather_point[1] - fy) ** 2,
        )
