#ifndef RECOMP_FUNC_REGISTRY_H_
#define RECOMP_FUNC_REGISTRY_H_

#include <stdint.h>

typedef struct RecompFuncEntry {
  const char *name;
  void *fn;
  uint32_t rom_addr;  // 24-bit ROM address this func was recompiled from
  int argc;           // 0 = void(), 1 = void(uint8), -1 = unsupported sig
} RecompFuncEntry;

extern const RecompFuncEntry recomp_func_registry[];
extern const int recomp_func_registry_count;

// Linear scan by name. NULL if not found.
const RecompFuncEntry *recomp_func_registry_lookup(const char *name);

#endif
