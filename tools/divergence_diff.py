"""
divergence_diff.py — cross-runtime divergence finder for snesrecomp + oracle.

Connects to the recomp runtime (default port 4377) and the oracle runtime
(default port 4378), pulls per-frame state from both ring buffers, and
reports the first frame at which any monitored state diverges.

This replaces the inert in-runtime verify_pass / first_failure / diff_count
mechanism (which was inherited from the smw-rev fork and never wired to
compare against an external oracle). Comparison belongs in an external
tool, not in the runtime — the runtime's job is to expose state.

Usage:
    python tools/divergence_diff.py                  # binary-search WRAM divergence
    python tools/divergence_diff.py --frame 425      # diff a single frame
    python tools/divergence_diff.py --start 0 --end 500 --step 25
    python tools/divergence_diff.py --field game_mode  # narrow to one field
"""

from __future__ import annotations
import argparse
import json
import socket
import sys
import time

DEFAULT_RECOMP_PORT = 4377
DEFAULT_ORACLE_PORT = 4378
WRAM_BYTES = 0x20000


class Runtime:
    """One TCP connection to a snesrecomp-style debug_server."""

    def __init__(self, port: int, name: str):
        self.port = port
        self.name = name
        self.sock = socket.socket()
        self.sock.settimeout(15)
        self.sock.connect(("127.0.0.1", port))
        self.f = self.sock.makefile("rwb")
        # Eat the initial banner emitted on connect.
        self.f.readline()
        self.last_frame = -1

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def cmd(self, line: str) -> dict:
        """Send a command, parse the JSON response. Server emits one
        '{"connected":true,"frame":N}' banner at connect, then one line
        per command response — no per-response preamble."""
        self.sock.sendall((line + "\n").encode())
        body = self.f.readline().decode().strip()
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{self.name}: bad json: {body[:200]}") from e

    def current_frame(self) -> int:
        """Newest frame in the ring buffer (server's actual progress)."""
        r = self.cmd("history")
        h = r.get("history", {})
        return int(h.get("newest", -1))

    def step(self, n: int) -> int:
        """Step the runtime forward N frames, blocking until done.
        Returns the new newest frame. Requires the runtime was launched
        with --paused so we control advancement explicitly."""
        before = self.current_frame()
        self.cmd(f"step {n}")
        target = before + n
        deadline = time.time() + max(30.0, n * 0.05)
        while time.time() < deadline:
            cur = self.current_frame()
            if cur >= target:
                return cur
            time.sleep(0.1)
        return self.current_frame()

    def dump_wram(self, frame: int) -> bytes | None:
        r = self.cmd(f"dump_frame_wram {frame} 0 {WRAM_BYTES}")
        if "hex" not in r:
            return None
        return bytes.fromhex(r["hex"])

    def get_frame(self, frame: int) -> dict | None:
        r = self.cmd(f"get_frame {frame}")
        return None if "error" in r else r


def wait_for_frame(rs: list[Runtime], target: int, timeout_s: float = 60.0) -> bool:
    """Block until every runtime has reached `target`."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if all(rt.current_frame() >= target for rt in rs):
            return True
        time.sleep(0.5)
    return False


def diff_wram(a: bytes, b: bytes, max_report: int = 16) -> tuple[int, list[tuple[int, int, int]]]:
    """Return (count_of_diffs, [(addr, a_byte, b_byte)] up to max_report)."""
    diffs: list[tuple[int, int, int]] = []
    n = 0
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            n += 1
            if len(diffs) < max_report:
                diffs.append((i, x, y))
    return n, diffs


def cmd_scan(args, recomp: Runtime, oracle: Runtime) -> int:
    """Run a coarse scan across checkpoint frames, then bisect to the first."""
    if args.advance:
        # Both runtimes assumed launched with --paused. Step them in lockstep
        # to args.end so the scanned range is in their ring buffers.
        print(f"# stepping both runtimes to frame {args.end}", flush=True)
        rf = recomp.step(args.end)
        of = oracle.step(args.end)
        print(f"# recomp at {rf}, oracle at {of}", flush=True)

    checkpoints = list(range(args.start, args.end + 1, args.step))
    if checkpoints[-1] != args.end:
        checkpoints.append(args.end)

    print(f"# scanning frames {args.start}..{args.end} step={args.step}", flush=True)
    last_match: int | None = None
    first_diverge: int | None = None
    for f in checkpoints:
        if not wait_for_frame([recomp, oracle], f):
            print(f"frame={f:5d}  TIMEOUT waiting for both runtimes", flush=True)
            continue
        rw = recomp.dump_wram(f)
        ow = oracle.dump_wram(f)
        if rw is None or ow is None:
            print(f"frame={f:5d}  dump failed (recomp={rw is not None}, oracle={ow is not None})", flush=True)
            continue
        if rw == ow:
            print(f"frame={f:5d}  MATCH ({len(rw)} bytes)", flush=True)
            last_match = f
        else:
            n, head = diff_wram(rw, ow)
            samples = ", ".join(f"${a:05X}(r={x:02x},o={y:02x})" for a, x, y in head[:6])
            print(f"frame={f:5d}  DIVERGE {n} bytes — {samples}", flush=True)
            first_diverge = f
            break

    if first_diverge is None:
        print("# no divergence in scanned range", flush=True)
        return 0
    if last_match is None:
        print(f"# divergence already present at start frame {args.start}; bisect cannot localise earlier", flush=True)
        return 0

    print(f"# bisecting between {last_match} (match) and {first_diverge} (diverge)", flush=True)
    lo, hi = last_match, first_diverge
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if not wait_for_frame([recomp, oracle], mid):
            print(f"# bisect: timeout at {mid}; aborting", flush=True)
            break
        rw = recomp.dump_wram(mid)
        ow = oracle.dump_wram(mid)
        if rw is None or ow is None:
            print(f"# bisect: dump failed at {mid}; aborting", flush=True)
            break
        if rw == ow:
            print(f"  bisect mid={mid} MATCH", flush=True)
            lo = mid
        else:
            n, head = diff_wram(rw, ow)
            samples = ", ".join(f"${a:05X}(r={x:02x},o={y:02x})" for a, x, y in head[:6])
            print(f"  bisect mid={mid} DIVERGE {n} bytes — {samples}", flush=True)
            hi = mid

    print(f"# first-divergent frame: {hi} (last match: {lo})", flush=True)
    rw = recomp.dump_wram(hi)
    ow = oracle.dump_wram(hi)
    if rw and ow:
        n, head = diff_wram(rw, ow, max_report=64)
        print(f"# {n} divergent bytes at frame {hi}; first 64:", flush=True)
        for a, x, y in head:
            print(f"  ${a:05X}: recomp={x:02x}  oracle={y:02x}", flush=True)
    return 0


def cmd_watch(args, recomp: Runtime, oracle: Runtime) -> int:
    """Watch a specific WRAM byte (or short range) across stepped frames.
    Both runtimes must be launched --paused; this stepper drives them together.
    After step(N), the runtime has recorded frames [prev+1 .. prev+N]; we dump
    each runtime's own newest frame index so the recomp/oracle frame-number
    offset is handled implicitly."""
    print(f"# watching ${args.addr:04X}+{args.length} for {args.frames} frames", flush=True)
    addr_hex = f"{args.addr:x}"
    print(f"{'r/o#':>8} | {'recomp':<32} | {'oracle':<32}", flush=True)
    print("-" * 80, flush=True)
    for _ in range(args.frames):
        rf = recomp.step(1)
        of = oracle.step(1)
        rr = recomp.cmd(f"dump_frame_wram {rf} {addr_hex} {args.length}")
        oo = oracle.cmd(f"dump_frame_wram {of} {addr_hex} {args.length}")
        rh = rr.get("hex", rr.get("error", "?"))
        oh = oo.get("hex", oo.get("error", "?"))
        marker = "" if rh == oh else "  <- DIFFER"
        print(f"{rf:>3}/{of:<3} | {rh:<32} | {oh:<32}{marker}", flush=True)
    return 0


def cmd_trace(args, recomp: Runtime, oracle: Runtime) -> int:
    """Enable per-runtime addr-watch on `--addr`, step both N frames,
    dump both logs side-by-side. Catches every WRAM change at that
    address that survives the runtime's 5ms watchpoint poll interval —
    fast intra-frame writes that get clobbered may be missed."""
    addr_hex = f"{args.addr:x}"
    print(f"# trace_addr ${args.addr:04X} on both runtimes, stepping {args.frames} frames", flush=True)
    print(f"recomp init: {recomp.cmd(f'trace_addr {addr_hex}')}", flush=True)
    print(f"oracle init: {oracle.cmd(f'trace_addr {addr_hex}')}", flush=True)
    for _ in range(args.frames):
        recomp.step(1)
        oracle.step(1)
    rt = recomp.cmd("get_trace")
    ot = oracle.cmd("get_trace")
    print(f"\n=== recomp writes to ${args.addr:04X} ({rt.get('entries', 0)} entries) ===", flush=True)
    for e in rt.get("log", []):
        stack = " > ".join(e.get("stack", [])) or "(no stack)"
        print(f"  f={e['f']}  {e['old']} -> {e['new']}  func={e['func']}  stack=[{stack}]", flush=True)
    print(f"\n=== oracle writes to ${args.addr:04X} ({ot.get('entries', 0)} entries) ===", flush=True)
    for e in ot.get("log", []):
        stack = " > ".join(e.get("stack", [])) or "(no stack)"
        print(f"  f={e['f']}  {e['old']} -> {e['new']}  func={e['func']}  stack=[{stack}]", flush=True)
    return 0


def cmd_frame(args, recomp: Runtime, oracle: Runtime) -> int:
    """Diff a single frame in detail."""
    if not wait_for_frame([recomp, oracle], args.frame):
        print(f"timeout waiting for frame {args.frame}", flush=True)
        return 1
    rw = recomp.dump_wram(args.frame)
    ow = oracle.dump_wram(args.frame)
    if rw is None or ow is None:
        print(f"dump failed (recomp={rw is not None}, oracle={ow is not None})", flush=True)
        return 1
    n, head = diff_wram(rw, ow, max_report=args.max_report)
    print(f"frame={args.frame}  {n} divergent bytes (showing up to {args.max_report}):", flush=True)
    for a, x, y in head:
        print(f"  ${a:05X}: recomp={x:02x}  oracle={y:02x}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recomp-port", type=int, default=DEFAULT_RECOMP_PORT)
    p.add_argument("--oracle-port", type=int, default=DEFAULT_ORACLE_PORT)
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("scan", help="binary-search WRAM divergence (default)")
    sp.add_argument("--start", type=int, default=0)
    sp.add_argument("--end", type=int, default=500)
    sp.add_argument("--step", type=int, default=25)
    sp.add_argument("--advance", action="store_true",
                    help="step both runtimes (assumed launched --paused) to --end before scanning")

    fp = sub.add_parser("frame", help="diff a single frame in detail")
    fp.add_argument("frame", type=int)
    fp.add_argument("--max-report", type=int, default=64)

    wp = sub.add_parser("watch", help="step both runtimes and watch a WRAM byte/range each frame")
    wp.add_argument("--addr", type=lambda s: int(s, 0), default=0x03)
    wp.add_argument("--length", type=int, default=1)
    wp.add_argument("--frames", type=int, default=20)

    tp = sub.add_parser("trace", help="enable trace_addr on both runtimes, step N frames, dump both logs")
    tp.add_argument("--addr", type=lambda s: int(s, 0), default=0x03)
    tp.add_argument("--frames", type=int, default=5)

    # Default sub-command if none given.
    args = p.parse_args(argv if argv else ["scan"])
    if args.cmd is None:
        args = p.parse_args(["scan", *argv])

    recomp = Runtime(args.recomp_port, "recomp")
    oracle = Runtime(args.oracle_port, "oracle")
    try:
        if args.cmd == "frame":
            return cmd_frame(args, recomp, oracle)
        if args.cmd == "watch":
            return cmd_watch(args, recomp, oracle)
        if args.cmd == "trace":
            return cmd_trace(args, recomp, oracle)
        return cmd_scan(args, recomp, oracle)
    finally:
        recomp.close()
        oracle.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
