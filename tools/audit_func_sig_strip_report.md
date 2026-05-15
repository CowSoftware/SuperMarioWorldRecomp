# audit_func_sig_strip — report

v2 codegen ignores `sig:` entirely; the `# AUTO`/`# MANUAL`
markers were v1-era provenance tags. Both are safe to strip.

| Bank | Lines mutated | sig: (func) | sig: (name) | bare AUTO | bare MANUAL | AUTO + prose | MANUAL + prose |
|------|---------------|-------------|-------------|-----------|-------------|--------------|----------------|
| bank00.cfg | 350 | 303 | 39 | 150 | 156 | 1 | 1 |
| bank01.cfg | 484 | 445 | 39 | 76 | 358 | 0 | 2 |
| bank02.cfg | 310 | 289 | 7 | 228 | 58 | 1 | 0 |
| bank03.cfg | 234 | 42 | 6 | 69 | 144 | 1 | 1 |
| bank04.cfg | 121 | 3 | 2 | 71 | 48 | 0 | 0 |
| bank05.cfg | 99 | 13 | 0 | 85 | 6 | 1 | 3 |
| bank07.cfg | 8 | 1 | 0 | 7 | 0 | 0 | 0 |
| bank0c.cfg | 112 | 6 | 0 | 100 | 12 | 0 | 0 |
| bank0d.cfg | 187 | 48 | 0 | 119 | 65 | 1 | 0 |
| **TOTAL** | **1905** | **1150** | **93** | **905** | **847** | **5** | **7** |
