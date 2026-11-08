class DialogueFlags:
    """Facts later lines and choices can require. Values are stored as strings."""

    def __init__(self, values=None):
        self.values = {str(k): str(v) for k, v in (values or {}).items()}

    def get(self, key, default=""):
        return self.values.get(str(key), default)

    def set(self, key, value="1"):
        self.values[str(key)] = str(value)

    def has(self, key):
        return self.get(key) not in ("", "0", "false", "False")

    def matches(self, require) -> bool:
        """None passes. A string is a flag, `not:flag`, or `flag=value`. A dict is flag=value pairs."""
        if require is None or require == "":
            return True
        if isinstance(require, str):
            if require.startswith("not:"):
                return not self.has(require[4:])
            if "=" in require:
                key, _, val = require.partition("=")
                return self.get(key) == val
            return self.has(require)
        if isinstance(require, dict):
            return all(self.get(key) == str(val) for key, val in require.items())
        return False
