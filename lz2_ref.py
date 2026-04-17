#!/usr/bin/env python3
"""LZ2 reference decoder for SMW graphics decompression.

Ported literally from SMWDisX/bank_00.asm CODE_00B8DE..CODE_00B97C (the
DecompressTo routine) and the GFX file pointer tables at $00:B992/B9C4/B9F6.

Pure function: takes ROM bytes + GFX file index, returns decompressed bytes.
No dependency on the recomp build. Reference oracle.
"""

import sys
from pathlib import Path

LOROM_BANK_SIZE = 0x8000
LOROM_BASE      = 0x8000  # bank-local address where LoROM mapping begins


def lorom(rom: bytes, addr24: int) -> int:
    """Translate a 24-bit SNES LoROM address to a flat ROM file offset."""
    bank = (addr24 >> 16) & 0xFF
    lo   = addr24 & 0xFFFF
    if lo < LOROM_BASE:
        raise ValueError(f"LoROM access below $8000: {addr24:06X}")
    return ((bank & 0x7F) * LOROM_BANK_SIZE) + (lo - LOROM_BASE)


def gfx_source_addr(rom: bytes, j: int) -> int:
    """Read the 24-bit source address for GFX file J from the dispatch tables."""
    lo   = rom[lorom(rom, 0x00B992 + j)]
    hi   = rom[lorom(rom, 0x00B9C4 + j)]
    bank = rom[lorom(rom, 0x00B9F6 + j)]
    return (bank << 16) | (hi << 8) | lo


def decompress(rom: bytes, src_addr: int, max_out: int = 0x10000) -> tuple[bytes, int]:
    """Decompress an LZ2 stream beginning at src_addr (24-bit SNES address).

    Returns (decompressed_bytes, src_consumed).
    src_consumed is the count of source bytes read including the $FF terminator.
    """
    out = bytearray()
    src = src_addr
    src_start = src

    def fetch() -> int:
        nonlocal src
        # ReadByte at $00:B983: read [GraphicsCompPtr], advance lo, on bank cross
        # set lo=$8000 and bank++. The 24-bit src tracks both transparently here,
        # because lo wrapping from $FFFF→$0000 in our representation crosses to
        # the next bank — but the 65816 reset to $8000, not $0000. We replicate.
        b = rom[lorom(rom, src)]
        lo = src & 0xFFFF
        new_lo = (lo + 1) & 0xFFFF
        if new_lo == 0:
            # bank cross: lo goes to $8000, bank++
            bank = ((src >> 16) & 0xFF) + 1
            src = (bank << 16) | 0x8000
        else:
            src = (src & 0xFF0000) | new_lo
        return b

    while len(out) < max_out:
        cmd_byte = fetch()
        if cmd_byte == 0xFF:
            break

        # Decode command + length:
        #   non-extended: top 3 bits = cmd, bottom 5 bits = length-1
        #   extended (top 3 bits == 7): cmd in bits 4..2, length is 10-bit
        #     ((cmd_byte & 3) << 8) | next_byte
        if (cmd_byte & 0xE0) == 0xE0:
            cmd_high3 = (cmd_byte << 3) & 0xE0
            length    = (((cmd_byte & 0x03) << 8) | fetch()) + 1
        else:
            cmd_high3 = cmd_byte & 0xE0
            length    = (cmd_byte & 0x1F) + 1

        if cmd_high3 == 0x00:
            # Direct copy: copy `length` source bytes verbatim.
            for _ in range(length):
                out.append(fetch())
        elif cmd_high3 == 0x20:
            # Byte fill: read 1 byte, write it `length` times.
            b = fetch()
            for _ in range(length):
                out.append(b)
        elif cmd_high3 == 0x40:
            # Word fill (alternating two bytes).
            b0 = fetch()
            b1 = fetch()
            for i in range(length):
                out.append(b0 if (i & 1) == 0 else b1)
        elif cmd_high3 == 0x60:
            # Incremental fill: start byte, +1 each step.
            b = fetch()
            for _ in range(length):
                out.append(b & 0xFF)
                b += 1
        elif cmd_high3 & 0x80:
            # Back-reference: copy `length` bytes from earlier in OUTPUT buffer.
            # SMW US (no ver_has_rev_gfx) byte order via the XBA pattern at
            # CODE_00B966: ReadByte → A=byte0; XBA → B=byte0; ReadByte → A=byte1;
            # TAX (no second XBA) → X = A_full = (B<<8)|A_low = (byte0<<8)|byte1.
            # So byte0 is HIGH, byte1 is LOW.
            byte0 = fetch()
            byte1 = fetch()
            offset = (byte0 << 8) | byte1
            for _ in range(length):
                out.append(out[offset])
                offset += 1
        else:
            raise ValueError(f"Unknown cmd_high3 {cmd_high3:#x} at out len {len(out)}")

    return bytes(out), src - src_start


def main():
    if len(sys.argv) < 3:
        print("usage: lz2_ref.py <smw.sfc> <gfx_index_hex> [out_file]", file=sys.stderr)
        sys.exit(2)
    rom_path = Path(sys.argv[1])
    j = int(sys.argv[2], 16)
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    rom = rom_path.read_bytes()
    if len(rom) % 1024 == 512:
        rom = rom[512:]  # strip SMC header
    src = gfx_source_addr(rom, j)
    print(f"GFX {j:02X}: source = ${src:06X}", file=sys.stderr)
    data, consumed = decompress(rom, src)
    print(f"  decompressed {len(data)} bytes from {consumed} source bytes", file=sys.stderr)
    if out_path:
        out_path.write_bytes(data)
        print(f"  wrote {out_path}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
