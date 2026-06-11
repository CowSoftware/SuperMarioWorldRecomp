import sys
sys.path.insert(0, "tools")
from dbg import Dbg

d = Dbg()
print(d.cmd("loadstate 3"))
d.wait(4)
cam = d.u16(0x1A)
print("mode=0x%02x camera=%d player_x=%d" % (d.u8(0x100), cam, d.u16(0x94)))
N = 20
status = d.read(0x14C8, N)
xlo = d.read(0x00E4, N)
xhi = d.read(0x14E0, N)
xoff = d.read(0x15A0, N)
oidx = d.read(0x15EA, N)
print(" k stat screenx xoff oam_idx tile0_x tile0_y tile0_xhigh-from-buffer")
# OAM high table $0420: 2 bits per OAM slot of 4 (x-high + size). 1 byte covers 4 sprite-tiles.
hi = d.read(0x0420, 0x20)
for k in range(N):
    if status[k] == 0:
        continue
    sx = (xlo[k] | (xhi[k] << 8)) - cam
    sx = ((sx + 0x8000) & 0xFFFF) - 0x8000
    oi = oidx[k]
    tx = d.u8(0x200 + oi)
    ty = d.u8(0x200 + oi + 1)
    # x-high bit for this OAM slot: slot index = oi>>2; byte = hi[slot>>2]; within byte 2 bits per slot
    slot = oi >> 2
    hibyte = hi[slot >> 2]
    xhigh = (hibyte >> ((slot & 3) * 2)) & 1
    rawx = tx | (xhigh << 8)
    print("%2d 0x%02x %6d  %d  0x%02x   %3d    %3d    xhigh=%d rawOAMx=%d" %
          (k, status[k], sx, xoff[k], oi, tx, ty, xhigh, rawx))
