import os

import pygame


class ImageCache:
    """Images loaded once and kept for the whole run, shared by everything that draws them.

    A surface held here never changes and is never freed or replaced, so the GPU backend
    packs it into its sprite atlas the first time it is drawn (holds()). Its dicts are read
    and written only through these methods, so holds() knows every surface.
    """
    _images = {}
    _folder_cache = {}
    _scaled_cache = {}
    _held_ids = set()  # id() of every surface in the three dicts above

    @staticmethod
    def _normalize_path(path):
        return os.path.abspath(os.path.normpath(path))

    @staticmethod
    def _scale_key(scale):
        if scale is None:
            return None
        if isinstance(scale, (list, tuple)):
            return tuple(scale)
        return scale

    @staticmethod
    def folder_cache_key(folder, scale=None):
        return (ImageCache._normalize_path(folder), ImageCache._scale_key(scale))

    @staticmethod
    def holds(surface):
        """True for a surface this cache holds: it never changes and lives for the run."""
        return id(surface) in ImageCache._held_ids

    @staticmethod
    def clear():
        """Forget every image (tests)."""
        ImageCache._images.clear()
        ImageCache._folder_cache.clear()
        ImageCache._scaled_cache.clear()
        ImageCache._held_ids.clear()

    @staticmethod
    def frames(key):
        """The frame list stored under `key` (folder_cache_key), or None."""
        return ImageCache._folder_cache.get(key)

    @staticmethod
    def keep_frames(key, frames):
        """Store a frame list under `key` (folder_cache_key) and return the stored list.

        A key that already has frames keeps them: held surfaces are never replaced.
        """
        kept = ImageCache._folder_cache.setdefault(key, frames)
        if kept is frames:
            ImageCache._held_ids.update(id(frame) for frame in frames)
        return kept

    @staticmethod
    def load_image(path):
        """Load an image from a path, using the cache to avoid reloading from disk."""
        norm = ImageCache._normalize_path(path)
        image = ImageCache._images.get(norm)
        if image is None:
            image = pygame.image.load(norm)
            try:
                image = image.convert_alpha()
            except pygame.error:
                pass  # no display mode (headless server, tests): keep the file's own format
            ImageCache._images[norm] = image
            ImageCache._held_ids.add(id(image))
        return image

    @staticmethod
    def load_scaled(path, size):
        """Load and scale an image, caching by normalized path and target size."""
        scale = ImageCache._scale_key(size)
        if scale is None:
            raise ValueError("size is required for load_scaled")
        key = (ImageCache._normalize_path(path), scale)
        cached = ImageCache._scaled_cache.get(key)
        if cached is None:
            base = ImageCache.load_image(path)
            cached = pygame.transform.scale(base, tuple(scale))
            ImageCache._scaled_cache[key] = cached
            ImageCache._held_ids.add(id(cached))
        return cached

    @staticmethod
    def load_smooth(path, size):
        """Like load_scaled, but filtered smoothly (smoothscale): for painted art shown at a
        size other than it was painted at, which nearest-neighbour scaling leaves jagged."""
        scale = ImageCache._scale_key(size)
        if scale is None:
            raise ValueError("size is required for load_smooth")
        key = (ImageCache._normalize_path(path), scale, "smooth")
        cached = ImageCache._scaled_cache.get(key)
        if cached is None:
            base = ImageCache.load_image(path)
            cached = pygame.transform.smoothscale(base, tuple(scale))
            ImageCache._scaled_cache[key] = cached
            ImageCache._held_ids.add(id(cached))
        return cached
