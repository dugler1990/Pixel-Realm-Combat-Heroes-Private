TRAVEL_TO_NODE = "travel_to_node"
GATHERING = "gathering"
TRAVEL_TO_DROPOFF = "travel_to_dropoff"
DELIVER = "deliver"
LOST = "lost"
QUEUED = "queued"


class GatherTask:
    def __init__(self, worker, node, source_row, dropoff, wallet):
        self.worker = worker
        self.node = node
        self.source_row = dict(source_row)
        self.dropoff = dropoff
        self.wallet = wallet
        self.state = TRAVEL_TO_NODE
        self.timer = 0.0
        self.category = str(source_row.get("category", ""))
        self.yield_amount = int(source_row.get("yieldAmount", 0))
        self.gather_duration = float(source_row.get("gatherDuration", 1))
        self._registered = False

    def _target_pos(self):
        if self.state in (TRAVEL_TO_NODE, GATHERING, QUEUED):
            return self.node.gather_point
        if self.dropoff is not None:
            return self.dropoff.rect.center
        return self.worker.rect.center

    def update(self, dt, move_callback):
        if self.state == LOST:
            return
        if self.dropoff is None:
            self.state = LOST
            if hasattr(self.worker, "gather_lost"):
                self.worker.gather_lost = True
            return

        if self.state == QUEUED:
            if self.node.can_accept_worker():
                self.node.register_worker()
                self._registered = True
                self.state = TRAVEL_TO_NODE
            return

        if self.state == TRAVEL_TO_NODE:
            if not self._registered:
                if self.node.can_accept_worker():
                    self.node.register_worker()
                    self._registered = True
                else:
                    self.state = QUEUED
                    return
            arrived = move_callback(self.worker, self._target_pos(), dt)
            if arrived:
                self.state = GATHERING
                self.timer = self.gather_duration
            return

        if self.state == GATHERING:
            self.timer -= float(dt or 0)
            if self.timer <= 0:
                self.node.mark_depleted()
                if self._registered:
                    self.node.unregister_worker()
                    self._registered = False
                self.state = TRAVEL_TO_DROPOFF
            return

        if self.state == TRAVEL_TO_DROPOFF:
            arrived = move_callback(self.worker, self._target_pos(), dt)
            if arrived:
                self.state = DELIVER
            return

        if self.state == DELIVER:
            if self.wallet is not None and self.category:
                self.wallet.add(self.category, self.yield_amount)
            if self.node.depleted:
                self.state = LOST
                return
            if self.node.can_accept_worker():
                self.node.register_worker()
                self._registered = True
                self.state = TRAVEL_TO_NODE
            else:
                self.state = QUEUED

    def cancel(self):
        if self._registered:
            self.node.unregister_worker()
            self._registered = False
