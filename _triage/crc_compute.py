import zlib, sys
with open('smw.sfc', 'rb') as f:
    data = f.read()
print(f'size={len(data)} bytes')
hdr = 512 if len(data) % 1024 == 512 else 0
crc = zlib.crc32(data[hdr:]) & 0xFFFFFFFF
print(f'crc32 (after stripping {hdr}-byte header) = 0x{crc:08X}')
