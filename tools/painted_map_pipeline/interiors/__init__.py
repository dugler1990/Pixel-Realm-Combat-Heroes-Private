"""Building interiors: paint the floor plan as flat classes, trace it, then render it.

The generator this replaces asked one call to invent the dungeon layout and render it in
stone, and gated only the byte-equality of the rim -- which passes on an image with two
unrelated floor plans in it. Splitting the two lets the layout be traced into polygons, and
those polygons then drive the chamber, the collision quads and the render pass's control
image from one source, so they cannot drift apart.
"""
