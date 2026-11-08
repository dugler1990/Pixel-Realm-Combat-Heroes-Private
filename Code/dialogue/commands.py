class CommandDispatcher:
    """Turns a graph command string into a call.

    `set_flag:name=value` is built in. The session registers `open_shop` to the
    trade window. `offer_quest` and `give_item` stay no-ops until those windows
    exist. Anything else is kept on `unknown` and still listed in pending.
    """

    def __init__(self, flags):
        self.flags = flags
        self.handlers = {}
        self.pending = []
        self.unknown = []

    def register(self, name, handler):
        self.handlers[name] = handler

    def dispatch(self, raw):
        if not raw:
            return
        name, _, arg = str(raw).partition(":")
        name = name.strip()
        arg = arg.strip()
        if not name:
            return
        if name == "set_flag":
            key, _, val = arg.partition("=")
            self.flags.set(key.strip(), (val.strip() or "1"))
            self.pending.append((name, arg))
            return
        self.pending.append((name, arg))
        handler = self.handlers.get(name)
        if handler is None:
            self.unknown.append((name, arg))
            return
        handler(arg)

    def take_pending(self):
        pending = self.pending
        self.pending = []
        return pending
