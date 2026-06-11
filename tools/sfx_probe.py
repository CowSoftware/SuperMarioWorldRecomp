#!/usr/bin/env python3
"""Missed-SFX probe over the always-on audio_trace port-traffic ring.

The runner records every CPU->APU port write ($2140-43), every SPC-side
port read that observed a new value, every SPC outPort write, and every
KON, all timestamped in native-sample time with the game frame in aux.
This probe QUERIES that ring backward — it never arms anything and the
game keeps running.

Per sound command (a nonzero CPU write to an APU port) the fate is one of:
  SEEN      — an SPC read of that port observed the value before the CPU
              replaced it; a KON followed within the window.
  SEEN-NOKON— the engine read the value but no KON followed (engine-level
              rejection: channel arbitration, priority, APU-side logic).
  LOST      — the CPU overwrote the port (or zeroed it) before any SPC
              read observed the value: the engine never saw the command.
              This is the transport-drop signature.

Usage:
  python tools/sfx_probe.py stats              # counters incl. overwrites
  python tools/sfx_probe.py chain [N]          # analyze last N events (default 8000)
  python tools/sfx_probe.py watch              # live: poll + report new commands
  python tools/sfx_probe.py mark <note>        # print a frame-stamped marker line
"""
import sys
import time

# SMW queue->port mapping (SMWDisX bank_00 NMI upload: SPCIOn = $1DF9+n
# mirrors, stored to HW_APUIOn = $2140+n each NMI, mirrors then zeroed —
# so every command lives on its port for exactly one frame):
#   port0 <- $1DF9  SFX bank 1 (jump, hit, etc.)
#   port1 <- $1DFA  SFX bank 2
#   port2 <- $1DFB  music (written only when loading a song)
#   port3 <- $1DFC  SFX bank 3 (coin, etc.)
PORT_NAMES = {0: "$1DF9/sfx1", 1: "$1DFA/sfx2", 2: "$1DFB/music", 3: "$1DFC/sfx3"}

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from dbg import Dbg

# A KON this many native samples (32 kHz) after the SPC read still counts
# as caused by it. SMW's engine keys voices within a tick or two (~2 ms);
# 3200 samples = 100 ms is generous without crossing into the next sound.
KON_WINDOW = 3200


def fetch_events(d, first=0, max_per_call=8000):
    """Pull [first, head) from the event ring, all types."""
    out = []
    while True:
        r = d.cmd(f"audio_events {first} {max_per_call} 0")
        evs = r.get("events", [])
        if not evs:
            return out, r.get("oldest", 0)
        out.extend(evs)
        first = max(first, r.get("first", first)) + r.get("scanned", len(evs))
        if r.get("scanned", 0) < max_per_call:
            return out, r.get("oldest", 0)


def event_head(d):
    return d.cmd("audio_stats 0").get("event_count", 0)


def analyze(events):
    """Group port traffic into per-command chains. Returns list of dicts.

    With the port-write scheduler (cpu_ap events present), the APPLY is
    the authoritative port mutation — cpu_wr is just the request stamp,
    paired FIFO per port to report request->apply latency. Older traces
    without cpu_ap fall back to cpu_wr as the mutation timeline."""
    has_apply = any(e["t"] == "cpu_ap" for e in events)
    mutate_type = "cpu_ap" if has_apply else "cpu_wr"

    cmds = []          # all nonzero applied commands, in order
    open_cmd = [None] * 4   # port -> command dict awaiting an spc_rd
    kons = []          # (sample_idx, val) of KON writes
    reqs = [[] for _ in range(4)]  # per-port FIFO of unapplied cpu_wr stamps

    for e in events:
        t = e["t"]
        s = e["s"]
        if t == "reg":
            if e["adr"] == "0x4c" and int(e["val"], 16) != 0:
                kons.append((s, e["val"]))
            continue
        if t not in ("cpu_wr", "cpu_ap", "spc_rd"):
            continue
        port = int(e["adr"], 16) & 3
        val = int(e["val"], 16)
        frame = e["aux"]
        if has_apply and t == "cpu_wr":
            reqs[port].append({"s": s, "val": val, "frame": frame})
            continue
        if t == mutate_type:
            req_s = None
            if has_apply:
                # The HLE upload flushes the runner's queue without
                # emitting applies, leaving stale requests at the FIFO
                # head — skip past them to the first value match.
                q = reqs[port]
                for i, r in enumerate(q):
                    if r["val"] == val:
                        req_s = r["s"]
                        del q[: i + 1]
                        break
            prev = open_cmd[port]
            if prev is not None:
                prev["fate"] = "LOST"
                prev["lost_to"] = {"val": val, "frame": frame, "s": s}
            cmd = None
            if val != 0:
                cmd = {"port": port, "val": val, "frame": frame, "s": s,
                       "req_s": req_s,
                       "fate": "PENDING", "seen_s": None, "kon": None}
                cmds.append(cmd)
            open_cmd[port] = cmd
        else:  # spc_rd — the engine observed the port's current value
            cmd = open_cmd[port]
            if cmd is not None and val == cmd["val"]:
                cmd["fate"] = "SEEN"
                cmd["seen_s"] = s
                open_cmd[port] = None

    # attach KONs to SEEN commands within the window
    for c in cmds:
        if c["fate"] != "SEEN":
            continue
        for s, v in kons:
            if c["seen_s"] <= s <= c["seen_s"] + KON_WINDOW:
                c["kon"] = {"s": s, "val": v}
                break
        if c["kon"] is None:
            c["fate"] = "SEEN-NOKON"
    return cmds


def fmt(c):
    base = (f"f{c['frame']:>7}  {PORT_NAMES.get(c['port'], c['port']):<11}  "
            f"val=0x{c['val']:02x}  {c['fate']:<10}")
    if c["fate"] == "LOST":
        lt = c.get("lost_to", {})
        base += (f" overwritten by 0x{lt.get('val', 0):02x} "
                 f"at f{lt.get('frame', '?')} "
                 f"(+{lt.get('s', 0) - c['s']} samples)")
    elif c["kon"]:
        base += f" KON {c['kon']['val']} +{c['kon']['s'] - c['seen_s']} samples"
    if c.get("req_s") is not None:
        base += f"  [apply latency {c['s'] - c['req_s']} samples]"
    return base


def cmd_stats(d):
    st = d.cmd("audio_stats 5")
    keys = ["cpu_port_writes", "spc_port_reads_seen", "spc_port_reads_logged",
            "spc_port_writes", "cpu_port_reads_logged", "cpu_port_overwrites",
            "kon_writes", "reg_writes", "dropped", "drop_runs", "event_count"]
    for k in keys:
        print(f"{k:>24}: {st.get(k)}")


def cmd_chain(d, last_n):
    head = event_head(d)
    first = max(0, head - last_n)
    events, oldest = fetch_events(d, first)
    cmds = analyze(events)
    lost = [c for c in cmds if c["fate"] == "LOST"]
    nokon = [c for c in cmds if c["fate"] == "SEEN-NOKON"]
    print(f"# events [{max(first, oldest)}, {head})  "
          f"commands={len(cmds)} lost={len(lost)} seen-nokon={len(nokon)}")
    for c in cmds:
        print(fmt(c))


def cmd_watch(d):
    """Live mode: print every new sound command and its fate as it resolves.
    Commands stay pending until the next poll shows their outcome."""
    first = event_head(d)
    print(f"# watching from event {first} (frame {d.frame()}); Ctrl-C to stop")
    carry = []
    printed = set()  # (port, val, sample_idx) of already-reported commands
    while True:
        time.sleep(1.0)
        head = event_head(d)
        if head == first:
            continue
        events, _ = fetch_events(d, first)
        first = head
        # re-analyze carry + new so pending commands resolve across polls
        cmds = analyze(carry + events)
        for c in cmds:
            key = (c["port"], c["val"], c["s"])
            if c["fate"] == "PENDING" or key in printed:
                continue
            printed.add(key)
            print(fmt(c), flush=True)
        # carry raw events forward so pending commands can still resolve
        carry = carry + events
        if len(carry) > 32000:
            carry = carry[-16000:]
        if len(printed) > 100000:
            printed.clear()


def cmd_mark(d, note):
    print(f"MARK frame={d.frame()} wall={time.strftime('%H:%M:%S')} note={note}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    d = Dbg()
    op = sys.argv[1]
    if op == "stats":
        cmd_stats(d)
    elif op == "chain":
        cmd_chain(d, int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
    elif op == "watch":
        cmd_watch(d)
    elif op == "mark":
        cmd_mark(d, " ".join(sys.argv[2:]) or "-")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
