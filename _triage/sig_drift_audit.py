"""Find name/func declarations whose sig disagrees across bank cfgs."""
import re, glob

sigs = {}
for f in sorted(glob.glob('recomp/bank*.cfg')):
    m = re.search(r'bank(\w+)\.cfg', f)
    bank = m.group(1)
    with open(f) as fp:
        for line in fp:
            m = re.match(r'\s*(name|func)\s+([0-9a-fA-F]+)\s+(\w+)\s.*sig:(\S+)', line)
            if m:
                addr = m.group(2).lower()
                name = m.group(3)
                sig = m.group(4)
                sigs.setdefault((addr, name), []).append((bank, sig))

drift = 0
for (addr, name), entries in sorted(sigs.items()):
    sigset = set(s for _, s in entries)
    if len(sigset) > 1:
        print(f'{addr} {name}: {entries}')
        drift += 1
print(f'TOTAL drift: {drift}')
