#!/usr/bin/env python3
"""Locate C++ vtables in a stripped ARM ELF and print "<vaddr> <mangled-name>" for each.
Layout assumed: [offset_to_top][typeinfo_ptr][fn ptrs...] ; objects store pointer to first fn ptr.
Usage: vtmap.py <elf> <text_lo> <text_hi> <ro_lo> <ro_hi> <delta>
"""
import struct, sys, re

path, tlo, thi, rlo, rhi, delta = sys.argv[1:7]
tlo, thi, rlo, rhi, delta = (int(x, 0) for x in (tlo, thi, rlo, rhi, delta))
d = open(path, 'rb').read()

def rd(v):
    return struct.unpack_from('<I', d, v - delta)[0]

def cstr(v):
    o = v - delta
    e = d.index(b'\0', o)
    return d[o:e].decode('latin1')

def intext(v):
    return tlo <= (v & ~1) < thi and (v & 1)

def inro(v):
    return rlo <= v < rhi

seen = []
for v in range(rlo + 8, rhi - 4, 4):
    if all(intext(rd(v + 4 * i)) for i in range(8)):
        if not all(intext(rd(v + 4 * i)) for i in range(8, 9)):
            pass
        ti = rd(v - 4)
        name = ''
        if inro(ti):
            s = rd(ti + 4)
            if inro(s):
                name = cstr(s)
        if name:
            seen.append((v, name))
for v, n in seen:
    print(f"{v:#08x} {n}")
