#!/usr/bin/env python3
"""Automated widescreen sprite-margin verifier (no human in the loop).

Drives the running game into a level, walks right to scroll, then reports each
active sprite: screen-x (relative to camera), its xoffscreen flag, and whether
it is actually DRAWN (its OAM tile y != 0xF0) or PARKED off-screen.

Pass condition for widescreen: sprites whose screen-x lands in the margins
(< 0 or >= 256, up to the ~[-71,320) window) should be DRAWN, not parked.

    python tools/ws_check.py
"""
import sys
sys.path.insert(0, "tools")
from dbg import Dbg

CAM = 0x1A
GAME_MODE = 0x100
SPR_STATUS = 0x14C8
SPR_XLO, SPR_XHI = 0x00E4, 0x14E0
SPR_XOFF = 0x15A0
SPR_OAMIDX = 0x15EA
OAM = 0x200
N = 20


def to_level(d):
    if d.u8(GAME_MODE) == 0x14:
        return True
    # From overworld: enter the first level.
    for btn in ("b", "start", "a", "start"):
        d.press(btn, frames=10)
        d.wait(20)
        if d.u8(GAME_MODE) == 0x14:
            break
    for _ in range(60):
        if d.u8(GAME_MODE) == 0x14:
            return True
        d.wait(15)
    return d.u8(GAME_MODE) == 0x14


def sample(d, label):
    cam = d.u16(CAM)
    status = d.read(SPR_STATUS, N)
    xlo = d.read(SPR_XLO, N)
    xhi = d.read(SPR_XHI, N)
    xoff = d.read(SPR_XOFF, N)
    oidx = d.read(SPR_OAMIDX, N)
    print(f"\n[{label}] mode=0x{d.u8(GAME_MODE):02x} camera={cam}")
    print(" k stat screenx xoff oam_y drawn margin")
    for k in range(N):
        if status[k] == 0:
            continue
        sx = (xlo[k] | (xhi[k] << 8)) - cam
        sx = ((sx + 0x8000) & 0xFFFF) - 0x8000  # signed
        oam_y = d.u8(OAM + oidx[k] + 1)
        drawn = oam_y is not None and oam_y != 0xF0
        margin = "MARGIN" if (sx < 0 or sx >= 256) else ""
        print(f"{k:2d} 0x{status[k]:02x} {sx:6d}  {xoff[k]}   "
              f"0x{(oam_y or 0):02x}  {'Y' if drawn else 'park':4} {margin}")


def main():
    d = Dbg()
    if not to_level(d):
        print("could not reach a level (mode != 0x14)")
        return 1
    sample(d, "level start")
    # walk right to scroll the camera and surface margin sprites
    d.press("right", frames=180, release=False)
    d.wait(180)
    sample(d, "after walking right")
    d.cmd("set_controller none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
