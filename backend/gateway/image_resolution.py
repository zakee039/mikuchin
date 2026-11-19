"""Mikuchin-owned image size policy; official PolyStrata submodule stays untouched.

The native Gateway's future Image Worker will call ``allowed`` before creating
an upstream image job. Normal inference proxying does not use this yet.
"""
from __future__ import annotations

LOCAL_SIZES = (384, 512, 768, 1024)
STANDARD_SIZES = (
    (1024, 1024), (2048, 2048), (1536, 1024), (1024, 1536),
    (1536, 864), (2560, 1440), (3840, 2160), (2160, 3840),
)


def allowed(mode: str, width: int, height: int) -> bool:
    """Only WIDTH x HEIGHT; reject invalid dimensions instead of swapping them."""
    if type(width) is not int or type(height) is not int:
        return False
    if mode == "standard":
        return (width, height) in STANDARD_SIZES
    if mode == "all":  # Persisted name of the local recommended sizes pack.
        return width in LOCAL_SIZES and height in LOCAL_SIZES
    if mode == "square":  # Legacy API service capability, retained for users.
        return (width, height) == (1024, 1024)
    if mode == "custom":
        return all(256 <= side <= 4096 and side % 16 == 0
                   for side in (width, height))
    return False


def nearest16(value: int | float, *, default: int = 1024) -> int:
    try:
        number = float(value)
        if not -float("inf") < number < float("inf"):
            raise ValueError
    except (TypeError, ValueError):
        number = default
    return min(4096, max(256, int(number / 16 + .5) * 16))
