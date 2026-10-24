#!/usr/bin/env python3
"""Find ARM Thumb TBB/TBH jump tables in .text; print case index -> target.
Detection: bytes df e8 (0x 3) f0 = TBB ; df e8 (0xb|8) f0 = TBH (entries 16-bit).
Usage: python3 tools/tbl.py <elf> <start_hex> <end_hex> [nentries]
"""
import sys, struct
PATH, S, E = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
N = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0x14
B = open(PATH, 'rb').read()
v2p = lambda v: v if v < 0x2a000 else v - 0x8000

for a in range(S, E - 4):
    b = B[v2p(a):v2p(a) + 4]
    if b[0] == 0xdf and b[1] == 0xe8 and b[3] == 0xf0:
        tbh = bool(b[2] & 8)
        idx = b[2] & 0xf
        base = a + 4
        print(f'--- {"TBH" if tbh else "TBB"} @ {a:#x} idxreg=r{idx} table@{base:#x}')
        for i in range(N):
            if tbh:
                v = struct.unpack('<H', B[v2p(base + 2 * i):v2p(base + 2 * i) + 2])[0]
            else:
                v = B[v2p(base + i)]
            print(f'   [{i:#x}] raw={v:#x} target={base + 2 * v:#x}')
