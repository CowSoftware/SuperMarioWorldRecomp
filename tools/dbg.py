#!/usr/bin/env python3
"""Tiny client for the snesrecomp debug server (TCP 127.0.0.1:4377).

Lets the agent measure/drive the running game without the human in the loop:
read WRAM, inject controller input, read the frame counter, etc. Text protocol
— one command line per request, one newline-terminated JSON reply.

Reusable as a library (import) or CLI:
    python tools/dbg.py frame
    python tools/dbg.py read_ram 1a 4
    python tools/dbg.py set_controller start
"""
import json
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 4377

# button name -> mask (matches debug_server.c parse_controller_mask)
BTN = {"b": 0x001, "y": 0x002, "select": 0x004, "start": 0x008,
       "up": 0x010, "down": 0x020, "left": 0x040, "right": 0x080,
       "a": 0x100, "x": 0x200, "l": 0x400, "r": 0x800}


class Dbg:
    def __init__(self, host=HOST, port=PORT, timeout=5.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.buf = b""
        self.greeting = self._readline()  # server sends {"connected":true,...}

    def _readline(self):
        while b"\n" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk:
                break
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        txt = line.decode(errors="replace").strip()
        try:
            return json.loads(txt)
        except Exception:
            return {"raw": txt}

    def cmd(self, line):
        self.s.sendall((line.strip() + "\n").encode())
        return self._readline()

    # --- helpers ---
    def frame(self):
        return self.cmd("frame").get("frame")

    def read(self, addr, length):
        """Return bytes from WRAM at addr (int)."""
        r = self.cmd(f"read_ram {addr:x} {length}")
        hexs = r.get("hex", "")
        return bytes(int(b, 16) for b in hexs.split()) if hexs else b""

    def u8(self, addr):
        b = self.read(addr, 1)
        return b[0] if b else None

    def u16(self, addr):
        b = self.read(addr, 2)
        return (b[0] | (b[1] << 8)) if len(b) == 2 else None

    def press(self, *names, frames=8, release=True):
        """Hold the given buttons for ~frames frames, then release."""
        mask = 0
        for n in names:
            mask |= BTN[n.lower()]
        self.cmd(f"set_controller 0x{mask:03x}")
        self._wait_frames(frames)
        if release:
            self.cmd("set_controller none")
        return mask

    def _wait_frames(self, n):
        start = self.frame()
        if start is None:
            time.sleep(n / 60.0)
            return
        deadline = start + n
        for _ in range(2000):
            if (self.frame() or 0) >= deadline:
                return
            time.sleep(0.004)

    def wait(self, n):
        self._wait_frames(n)


if __name__ == "__main__":
    d = Dbg()
    if len(sys.argv) > 1:
        print(json.dumps(d.cmd(" ".join(sys.argv[1:]))))
    else:
        print(json.dumps(d.cmd("frame")))
