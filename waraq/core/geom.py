"""Page <-> screen coordinate transforms.

PDF user space has its origin at the bottom-left and y up.  A page is shown
by cropping to the crop box, rotating clockwise by ``rotation`` degrees
(page /Rotate plus any extra view rotation) and scaling by ``scale``
pixels per point; screen space has its origin at the top-left, y down.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PageGeom:
    x0: float
    y0: float
    x1: float
    y1: float
    rotation: int = 0       # 0, 90, 180, 270 clockwise
    scale: float = 1.0      # pixels per point

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def display_size(self) -> Tuple[float, float]:
        """Size in pixels after rotation."""
        if self.rotation % 180:
            return self.h * self.scale, self.w * self.scale
        return self.w * self.scale, self.h * self.scale

    def to_screen(self, x: float, y: float) -> Tuple[float, float]:
        s = self.scale
        u = (x - self.x0) * s
        v = (self.y1 - y) * s
        W, H = self.w * s, self.h * s
        r = self.rotation % 360
        if r == 0:
            return u, v
        if r == 90:
            return H - v, u
        if r == 180:
            return W - u, H - v
        return v, W - u

    def to_pdf(self, px: float, py: float) -> Tuple[float, float]:
        s = self.scale
        W, H = self.w * s, self.h * s
        r = self.rotation % 360
        if r == 0:
            u, v = px, py
        elif r == 90:
            u, v = py, H - px
        elif r == 180:
            u, v = W - px, H - py
        else:
            u, v = W - py, px
        return self.x0 + u / s, self.y1 - v / s

    def rect_to_screen(self, r):
        """PDF rect (x0, y0, x1, y1) -> normalised screen rect (l, t, r, b)."""
        a = self.to_screen(r[0], r[1])
        b = self.to_screen(r[2], r[3])
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def rect_to_pdf(self, l, t, r, b):
        a = self.to_pdf(l, t)
        c = self.to_pdf(r, b)
        return min(a[0], c[0]), min(a[1], c[1]), max(a[0], c[0]), max(a[1], c[1])


def norm_rect(r):
    return (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
