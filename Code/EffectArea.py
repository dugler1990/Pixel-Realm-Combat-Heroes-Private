class EffectArea:
    """
    Minimal EffectArea used in the QuadTree:
      - .rect  : pygame.Rect (game coords) used for broad-phase
      - .mask  : pygame.Mask (pixel mask in local surface coords) created at load time
      - .properties : dict from Tiled object properties
      - ._id : stable id string
      - .tmx_object : original pytmx object (kept for later reference)
    """
    def __init__(self, rect: "pygame.Rect", mask: "pygame.Mask", properties: dict = None, _id: str = None, tmx_object=None):
        self._id = _id if _id is not None else f"effect_{id(self)}"
        self.rect = rect
        self.mask = mask
        self.properties = properties or {}
        self._tmx_object = tmx_object
        # QuadTree expects direct left/top/right/bottom attributes
        self.left = rect.left
        self.top = rect.top
        self.right = rect.right
        self.bottom = rect.bottom

    def __hash__(self):
        return hash(self._id)

    def __eq__(self, other):
        return isinstance(other, EffectArea) and self._id == other._id

    def __repr__(self):
        return f"<EffectArea id={self._id} rect={self.rect} props={self.properties}>"
