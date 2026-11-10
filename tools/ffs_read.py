#!/usr/bin/env python3
"""Read files from the B6's internal flash file system (read-only).

  ffs_read.py NAME [NAME ...] [-d DIR] [--max-chunks N]    e.g. ffs_read.py FLST_SEQ.ZT2
  ffs_read.py --list                                       list all files on the pedal
  ffs_read.py --all                                        FLST_SEQ.ZT2 and every .ZD2 effect file

Request/reply pacing and message layouts follow zoom-zt2 (github.com/mungewell/zoom-zt2),
which reads the same file protocol on other Zoom pedals, cross-checked with Guitar Lab 7.3:
  Enter Sync/editor mode   50
  find                     60 25 00 00 <name> 00        (next: 60 26 00 00 * 00)
  open for read            60 20 02 <9 x 00> <name> 00
  read 512 bytes           60 22 14 2F 60 00 0C 00 04 00 00 00 ; the data arrives as the
                           reply to the following status poll 60 05 00:
                           60 04 .. .. <len:2 7-bit LE> <packed data> <crc:5>
  close                    60 21 40 00 00 00 00  (zoom-zt2 also sends flush 60 09; not needed for reads)
  Exit Sync/editor mode    51
Every message gets exactly one reply before the next is sent. Every message and reply is
logged (flushed immediately) to DIR/ffs.log, and the file is always closed on exit,
including on Ctrl-C / SIGTERM, because a file left open makes the pedal stop answering.
"""
import argparse
import binascii
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from b6lab.codec import unpack7  # noqa: E402
from b6lab.midi import B6  # noqa: E402

HDR = [0x52, 0x00, 0x6E]
STATUS = [0x60, 0x05, 0x00]
READ = [0x60, 0x22, 0x14, 0x2F, 0x60, 0x00, 0x0C, 0x00, 0x04, 0x00, 0x00, 0x00]


def _sigterm(*_):
    raise KeyboardInterrupt


class Session:
    def __init__(self, dev, log):
        self.dev, self.log = dev, log
        self.file_open = False

    def xfer(self, payload, timeout=2.0):
        """Send one message and return its single reply (None on timeout)."""
        msg = bytes(HDR + list(payload))
        self.log.write(f"{time.monotonic():.3f} > {msg.hex(' ')}\n")
        self.dev.send(msg)
        try:
            r = self.dev.recv_sysex(timeout)
        except TimeoutError:
            r = None
        self.log.write(f"{time.monotonic():.3f} < {r.hex(' ') if r is not None else 'TIMEOUT'}\n")
        self.log.flush()
        return r

    def find(self, name, first=True):
        r = self.xfer([0x60, 0x25 if first else 0x26, 0x00, 0x00] + list(name.encode()) + [0])
        st = self.xfer(STATUS)
        return r, st

    def list_files(self):
        names = []
        r, _ = self.find("*", True)
        while r is not None and len(r) > 14 and r[4] == 0x04 and len(names) < 2000:
            raw = bytes(r[14:])
            end = next((i for i, b in enumerate(raw) if b < 0x20 or b > 0x7E), len(raw))
            names.append(raw[:end].decode("ascii"))  # the B6 can leave a stray byte after the name
            r, _ = self.find("*", False)
        return names

    def download(self, name, max_chunks):
        r = self.xfer([0x60, 0x20, 0x02] + [0] * 9 + list(name.encode()) + [0])
        self.file_open = True
        if r is None or r[3:6] != bytes([0x60, 0x04, 0x20]):
            raise RuntimeError(f"open {name}: unexpected reply {r.hex(' ') if r else None}")
        data = bytearray()
        for n in range(max_chunks):
            self.xfer(STATUS)
            self.xfer(READ)
            p = self.xfer(STATUS)
            if p is None or len(p) < 15 or p[4] != 0x04:
                print(f"  chunk {n}: no data packet ({p.hex(' ')[:60] if p else 'timeout'})")
                break
            length = p[9] * 128 + p[8]
            if length == 0:
                break
            block = unpack7(bytes(p[10:10 + length + length // 7 + 1]))[:length]
            c = p[-5] | p[-4] << 7 | p[-3] << 14 | p[-2] << 21 | (p[-1] & 0x0F) << 28
            if c ^ 0xFFFFFFFF != binascii.crc32(block):
                raise RuntimeError(f"chunk {n}: CRC mismatch")
            data += block
            print(f"  chunk {n}: {length} bytes (total {len(data)})", flush=True)
        else:
            print(f"  stopped after --max-chunks {max_chunks}")
        self.close()
        return bytes(data)

    def close(self):
        if self.file_open:
            self.xfer([0x60, 0x21, 0x40, 0x00, 0x00, 0x00, 0x00])  # no 60 09 flush: read-only
            self.file_open = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("-d", "--dir", default="pedal-files")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true", help="read FLST_SEQ.ZT2 and every .ZD2 file")
    ap.add_argument("--max-chunks", type=int, default=400)
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    signal.signal(signal.SIGTERM, _sigterm)
    log = open(os.path.join(a.dir, "ffs.log"), "a")
    dev = B6.open()
    s = Session(dev, log)
    try:
        dev.drain()
        r = s.xfer([0x50])                                   # Enter Sync/editor mode
        print("enter sync:", r.hex(" ") if r else "TIMEOUT", flush=True)
        if r is None:
            sys.exit("pedal does not answer; turn it off and on")
        names = list(a.names)
        if a.list or a.all:
            for nm in s.list_files():
                if a.list:
                    print(nm)
                if a.all and nm.upper().endswith(".ZD2") and nm not in names:
                    names.append(nm)
        if a.all and "FLST_SEQ.ZT2" not in names:
            names.insert(0, "FLST_SEQ.ZT2")
        for nm in names:
            _, st = s.find(nm)
            print(f"{nm}: find -> {st.hex(' ') if st else 'TIMEOUT'}", flush=True)
            if st is None or st[-5:] != bytes(5):
                print(f"{nm}: not on the pedal, skipped", flush=True)
                continue
            data = s.download(nm, a.max_chunks)
            out = os.path.join(a.dir, nm)
            with open(out, "wb") as f:
                f.write(data)
            print(f"{nm}: wrote {len(data)} bytes to {out}", flush=True)
    finally:
        try:
            s.close()
            s.xfer([0x51])                                   # Exit Sync/editor mode
        finally:
            dev.close()
            log.close()


if __name__ == "__main__":
    main()
