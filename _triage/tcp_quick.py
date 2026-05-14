"""Tight one-shot TCP command for menu-drive iteration.

Connects to 127.0.0.1:4377, sends one command line, reads the first
complete JSON response (one line ending in \n) with a 2s ceiling so
the Bash invocation never auto-backgrounds. Closes cleanly so the
single-client debug_server immediately accepts the next caller.

`screenshot <path.png>` shorthand: captures to a sibling .bmp,
converts to PNG via System.Drawing (PowerShell), deletes the BMP.
The runtime only knows how to write BMP; PNG conversion is local.

Usage:
    python _triage/tcp_quick.py <cmd-line>

Examples:
    python _triage/tcp_quick.py ping
    python _triage/tcp_quick.py "set_controller start"
    python _triage/tcp_quick.py clear_controller
    python _triage/tcp_quick.py "screenshot _triage/menu_01.png"
    python _triage/tcp_quick.py frame
"""
import os
import socket
import subprocess
import sys
import time

HOST = "127.0.0.1"
PORT = 4377
DEADLINE_SEC = 2.0


def _convert_bmp_to_png(bmp_path: str, png_path: str) -> bool:
    """Use PowerShell + System.Drawing to convert BMP -> PNG, delete BMP.
    Returns True on success.
    """
    ps = (
        "Add-Type -AssemblyName System.Drawing; "
        f"$img = [System.Drawing.Image]::FromFile('{bmp_path}'); "
        f"$img.Save('{png_path}', [System.Drawing.Imaging.ImageFormat]::Png); "
        "$img.Dispose()"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        print(f"PNG_CONVERT_FAIL: {e}")
        return False
    if r.returncode != 0:
        print(f"PNG_CONVERT_FAIL: rc={r.returncode} stderr={r.stderr.strip()}")
        return False
    try:
        os.remove(bmp_path)
    except OSError:
        pass
    return True


def main() -> int:
    cmd = " ".join(sys.argv[1:]).strip()
    if not cmd:
        print("usage: tcp_quick.py <cmd...>", file=sys.stderr)
        return 2

    # screenshot foo.png -> screenshot foo.bmp (capture), convert, cleanup.
    png_target: "Optional[str]" = None  # type: ignore
    bmp_target: "Optional[str]" = None
    if cmd.lower().startswith("screenshot "):
        path = cmd[len("screenshot "):].strip().strip('"').strip("'")
        if path.lower().endswith(".png"):
            png_target = path
            bmp_target = path[:-4] + ".bmp"
            cmd = f"screenshot {bmp_target}"

    s = socket.socket()
    s.settimeout(DEADLINE_SEC)
    try:
        s.connect((HOST, PORT))
    except Exception as e:
        print(f"CONNECT_FAIL: {e}")
        return 3

    # First read the {"connected":...} banner emitted by the server on
    # accept. Drain it briefly so it doesn't appear in our output.
    s.settimeout(0.3)
    try:
        banner = b""
        while b"\n" not in banner:
            banner += s.recv(4096)
    except Exception:
        pass

    s.settimeout(DEADLINE_SEC)
    try:
        s.sendall(cmd.encode() + b"\n")
    except Exception as e:
        print(f"SEND_FAIL: {e}")
        s.close()
        return 4

    buf = b""
    t0 = time.time()
    try:
        while time.time() - t0 < DEADLINE_SEC:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()

    sys.stdout.write(buf.decode(errors="replace"))
    if not buf.endswith(b"\n"):
        sys.stdout.write("\n")

    # Post-process screenshot path: convert BMP -> PNG if requested.
    if png_target and bmp_target and b'"ok":true' in buf:
        if _convert_bmp_to_png(bmp_target, png_target):
            sys.stdout.write(f'{{"converted_png":"{png_target}"}}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())
