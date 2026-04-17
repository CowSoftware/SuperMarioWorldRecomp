/* Standalone harness for DecompressTo / DecompressTo_FetchByte / GraphicsDecompress.
 *
 * Links against NOTHING from the main build. Provides a minimal SNES runtime
 * (g_ram, g_rom, IndirPtr, IndirWriteByte, RomPtr_00, RecompStackPush stub,
 * WatchdogCheck with a hard iteration cap) and copies the three relevant
 * function bodies VERBATIM from src/gen/smw_00_gen.c.
 *
 * Goal: prove or disprove a bug in DecompressTo without booting the game.
 *
 *   harness.exe <smw.sfc> <gfx_index_hex> <out.bin>
 *
 * Writes 3072 bytes (one GFX file) of decompressed output to <out.bin>.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef uint8_t  uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef uint16   VoidP;

#pragma pack(push, 1)
typedef struct LongPtr {
    VoidP addr;
    uint8 bank;
} LongPtr;
#pragma pack(pop)

#define GET_WORD(p)        (*(uint16*)(p))
#define PAIR16(high, low)  ((uint16)((high) << 8) | (uint8)(low))

/* ---- minimal runtime ---------------------------------------------------- */

uint8        g_ram[0x20000];
const uint8 *g_rom = NULL;
const char  *g_last_recomp_func = "(none)";

static unsigned long g_iter_cap = 100000000UL;
static unsigned long g_iter_count = 0;

void RecompStackPush(const char *name) { g_last_recomp_func = name; }
void RecompStackPop(void)              { (void)0; }

void WatchdogCheck(void) {
    if (++g_iter_count > g_iter_cap) {
        fprintf(stderr,
            "harness watchdog: %lu iterations exceeded in %s, bailing\n",
            g_iter_count, g_last_recomp_func ? g_last_recomp_func : "?");
        exit(2);
    }
}

uint8 *RomPtr(uint32 addr) {
    /* LoROM: ((bank << 15) | (offs & 0x7fff)) & 0x3fffff */
    uint32 flat = (((addr >> 16) << 15) | (addr & 0x7fff)) & 0x3fffff;
    return (uint8 *)&g_rom[flat];
}
static inline const uint8 *RomPtr_00(uint16 addr) { return RomPtr(addr); }

static inline uint8 *IndirPtr(LongPtr ptr, uint16 offs) {
    uint32 a = (*(uint32 *)&ptr & 0xffffff) + offs;
    uint8  bank = (uint8)(a >> 16);
    if (bank >= 0x7e && bank <= 0x7f)
        return &g_ram[a & 0x1ffff];
    if ((a & 0xffff) < 0x2000)
        return &g_ram[a & 0x1ffff];
    return RomPtr(a);
}
static inline void IndirWriteByte(LongPtr ptr, uint16 offs, uint8 value) {
    uint8 *dst = IndirPtr(ptr, offs);
    dst[0] = value;
}

/* ---- VERBATIM from src/gen/smw_00_gen.c (lines 6903..7062) -------------- *
 * If you regen bank 00, re-extract these three function bodies and rebuild. */

uint8 DecompressTo_FetchByte(void);
int   DecompressTo(const uint8 *p8a, const uint8 *p0);
uint8 *GraphicsDecompress_(uint8 j);

int DecompressTo(const uint8 *p8a, const uint8 *p0) {  // 00b8de
  uint16 v1 = 0, v4 = 0, v5 = 0, v9 = 0, v11 = 0, v13 = 0, v15 = 0, v18 = 0, v21 = 0, v22 = 0, v23 = 0, v24 = 0, v26 = 0, v27 = 0;
  uint8 v2 = 0, tmp1 = 0, v3 = 0, tmp2 = 0, v6 = 0, tmp3 = 0, tmp4 = 0, tmp5 = 0, v7 = 0, v8 = 0, tmp6 = 0, tmp7 = 0, v10 = 0, v12 = 0, v14 = 0, v16 = 0, v17 = 0, v19 = 0, v20 = 0, v25 = 0;
  extern const char *g_last_recomp_func;
  g_last_recomp_func = "DecompressTo";
  RecompStackPush("DecompressTo");
  v1 = 0;
  label_b8e3:;
  WatchdogCheck();
  v2 = DecompressTo_FetchByte();
  tmp1 = ((v2 >= 0xff)) ? 1 : 0;
  if ((v2 - 0xff) != 0) goto label_b8ed;
  return v2;
  label_b8ed:;
  g_ram[0x8f] = v2;
  v3 = v2 & 0xe0;
  tmp2 = (((v2 & 0xe0) >= 0xe0)) ? 1 : 0;
  if (((v2 & 0xe0) - 0xe0) == 0) goto label_b8ff;
  v4 = (uint16)v2;
  v5 = v4 & 0x1f;
  goto label_b911;
  v3 = v5;
  label_b8ff:;
  v6 = g_ram[0x8f];
  tmp3 = (v6 >> 7) & 1;
  v6 <<= 1;
  tmp4 = (v6 >> 7) & 1;
  v6 <<= 1;
  tmp5 = (v6 >> 7) & 1;
  v6 <<= 1;
  v7 = v6 & 0xe0;
  v8 = DecompressTo_FetchByte();
  v9 = PAIR16((g_ram[0x8f]) & 3, v8);
  v5 = v9;
  v3 = v7;
  label_b911:;
  v5++;
  *(uint16*)(g_ram + 0x8d) = v5;
  if (v3 == 0) goto label_b930;
  if ((int8_t)v3 < 0) goto label_b966;
  tmp6 = (v3 >> 7) & 1;
  v3 <<= 1;
  if ((int8_t)v3 >= 0) goto label_b93f;
  tmp7 = (v3 >> 7) & 1;
  v3 <<= 1;
  if ((int8_t)v3 >= 0) goto label_b94c;
  v10 = DecompressTo_FetchByte();
  v11 = GET_WORD(g_ram + 0x8d);
  label_b926:;
  WatchdogCheck();
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v10);
  v10++;
  v1++;
  v11--;
  if (v11 != 0) goto label_b926;
  goto label_b8e3;
  v3 = v10;
  label_b930:;
  WatchdogCheck();
  v12 = DecompressTo_FetchByte();
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v12);
  v1++;
  v13 = GET_WORD(g_ram + 0x8d);
  v13--;
  *(uint16*)(g_ram + 0x8d) = v13;
  v11 = v13;
  if (v13 != 0) goto label_b930;
  goto label_b8e3;
  v3 = v12;
  label_b93f:;
  v14 = DecompressTo_FetchByte();
  v15 = GET_WORD(g_ram + 0x8d);
  label_b944:;
  WatchdogCheck();
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v14);
  v1++;
  v15--;
  if (v15 != 0) goto label_b944;
  v12 = v14;
  goto label_b8e3;
  v3 = v14;
  label_b94c:;
  v16 = DecompressTo_FetchByte();
  v17 = DecompressTo_FetchByte();
  v18 = GET_WORD(g_ram + 0x8d);
  label_b955:;
  WatchdogCheck();
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v16);
  v1++;
  v18--;
  if (v18 == 0) goto label_b963;
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v17);
  v1++;
  v18--;
  if (v18 != 0) goto label_b955;
  v16 = v17;
  label_b963:;
  goto label_b8e3;
  v3 = v16;
  label_b966:;
  v19 = DecompressTo_FetchByte();
  v20 = DecompressTo_FetchByte();
  v21 = PAIR16(v19, v20);
  label_b96e:;
  WatchdogCheck();
  v22 = v1;
  v23 = v21;
  v24 = v23;
  v1 = v22;
  v25 = IndirPtr(*(LongPtr*)(g_ram+0x0), v23)[0];
  IndirWriteByte(*(LongPtr*)(g_ram+0x0), v1, v25);
  v1++;
  v24++;
  v26 = (uint16)v25;
  v27 = GET_WORD(g_ram + 0x8d) - 1;
  *(uint16*)(g_ram + 0x8d) = v27;
  v21 = v24;
  if (v27 != 0) goto label_b96e;
  goto label_b8e3;
}

uint8 DecompressTo_FetchByte(void) {  // 00b983
  uint16 v1 = 0, v3 = 0;
  uint8 v2 = 0;
  extern const char *g_last_recomp_func;
  g_last_recomp_func = "DecompressTo_FetchByte";
  RecompStackPush("DecompressTo_FetchByte");
  v1 = GET_WORD(g_ram + 0x8a);
  v1++;
  v2 = IndirPtr(*(LongPtr*)(g_ram+0x8a), 0)[0];
  if (v1 != 0) goto label_b98f;
  v3 = 0x8000;
  g_ram[0x8c]++;
  v1 = v3;
  label_b98f:;
  *(uint16*)(g_ram + 0x8a) = v1;
  return v2;
}

uint8 *GraphicsDecompress_(uint8 j) {  // 00ba28
  uint16 v8 = 0;
  uint8 v1 = 0, v2 = 0, v3 = 0, v4 = 0, v5 = 0, v6 = 0, v7 = 0;
  extern const char *g_last_recomp_func;
  g_last_recomp_func = "GraphicsDecompress";
  RecompStackPush("GraphicsDecompress");
  v1 = j;
  v2 = RomPtr_00(0xb992)[j];
  g_ram[0x8a] = v2;
  v3 = RomPtr_00(0xb9c4)[j];
  g_ram[0x8b] = v3;
  v4 = RomPtr_00(0xb9f6)[j];
  g_ram[0x8c] = v4;
  v5 = 0;
  g_ram[0x0] = v5;
  v6 = 0xad;
  g_ram[0x1] = v6;
  v7 = 0x7e;
  g_ram[0x2] = v7;
  v8 = DecompressTo(g_ram + v2, g_ram + v5);
  j = v1;
  return NULL;
}

/* ---- main --------------------------------------------------------------- */

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <smw.sfc> <gfx_hex> <out.bin>\n", argv[0]);
        return 2;
    }
    const char *rom_path = argv[1];
    int j = (int)strtoul(argv[2], NULL, 16);
    const char *out_path = argv[3];

    FILE *f = fopen(rom_path, "rb");
    if (!f) { perror(rom_path); return 1; }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    /* strip 512-byte SMC header if present */
    long header = (sz % 1024 == 512) ? 512 : 0;
    fseek(f, header, SEEK_SET);
    long rom_sz = sz - header;
    uint8 *rom = (uint8 *)malloc((size_t)rom_sz);
    fread(rom, 1, (size_t)rom_sz, f);
    fclose(f);
    g_rom = rom;

    fprintf(stderr, "ROM: %s (%ld bytes after header strip)\n", rom_path, rom_sz);
    fprintf(stderr, "GFX %02X: source ptr table → ", j);
    uint8 lo   = ((const uint8 *)RomPtr_00(0xb992))[j];
    uint8 hi   = ((const uint8 *)RomPtr_00(0xb9c4))[j];
    uint8 bank = ((const uint8 *)RomPtr_00(0xb9f6))[j];
    fprintf(stderr, "$%02X:%02X%02X\n", bank, hi, lo);

    GraphicsDecompress_((uint8)j);

    fprintf(stderr, "iterations: %lu, last fn: %s\n",
            g_iter_count, g_last_recomp_func ? g_last_recomp_func : "?");

    /* GraphicsDecompress points dest at 7E:AD00, so output is g_ram[0xAD00..]. */
    FILE *out = fopen(out_path, "wb");
    if (!out) { perror(out_path); return 1; }
    fwrite(&g_ram[0xAD00], 1, 0x1000, out);
    fclose(out);
    fprintf(stderr, "wrote 4096 bytes from g_ram[0xAD00..0xBD00] to %s\n", out_path);
    return 0;
}
