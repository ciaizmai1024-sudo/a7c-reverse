#!/usr/bin/env python3
"""Dump vtables / pointer arrays from an ELF whose first LOAD maps paddr = vaddr - delta.
Usage: vtable_dump.py <elf> <delta> <vaddr> [count]
"""
import struct, sys

path, delta, v = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0)
cnt = int(sys.argv[4], 0) if len(sys.argv) > 4 else 32
d = open(path, 'rb').read()
base = 0
for i in range(cnt):
    off = v - delta + i * 4
    val = struct.unpack_from('<I', d, off)[0]
    print(f"{v + i*4:#08x}: {val:#08x}")
