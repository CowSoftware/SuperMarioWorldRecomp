import struct
with open(r'F:\Projects\snesrecomp\SuperMarioWorldRecomp\build\bin-x64-Oracle\smw.exe', 'rb') as f:
    data = f.read(0x1000)
e_lfanew = struct.unpack_from('<I', data, 0x3c)[0]
print(f'e_lfanew=0x{e_lfanew:x}')
sig = data[e_lfanew:e_lfanew+4]
print(f'sig={sig}')
file_header = data[e_lfanew+4:e_lfanew+0x18]
machine, n_sections, _, _, _, opt_size, _ = struct.unpack('<HHIIIHH', file_header)
print(f'machine=0x{machine:x} n_sections={n_sections} opt_hdr_size={opt_size}')
opt = data[e_lfanew+0x18:e_lfanew+0x18+opt_size]
magic = struct.unpack_from('<H', opt, 0)[0]
print(f'opt magic=0x{magic:x}')
size_of_image = struct.unpack_from('<I', opt, 56)[0]
size_of_headers = struct.unpack_from('<I', opt, 60)[0]
print(f'SizeOfImage={size_of_image} (={size_of_image/(1024*1024):.1f}MB)')
print(f'SizeOfHeaders={size_of_headers}')
sec_off = e_lfanew + 0x18 + opt_size
for i in range(n_sections):
    sh = data[sec_off + i*40 : sec_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('ascii', errors='replace')
    vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', sh, 8)
    print(f'  section {name!r}: VirtualSize={vsize/(1024*1024):.1f}MB rawSize={rsize/(1024*1024):.1f}MB')
