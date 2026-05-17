"""Modular RTS/throne-mode subsystem.

This package is intentionally kept independent from Level4 so it can later be
hosted by a standalone RTS game state.
"""

from .session import RtsSession

__all__ = ["RtsSession"]
