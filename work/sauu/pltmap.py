#!/usr/bin/env python3
"""Exact PLT-stub -> import-name map for ARM32 ELF (mixed ARM/Thumb PLT).

r2/rabin2 place the symbol label at the *middle* of a PLT entry, so "bl fcn.0000ab7c"
cannot be read off their listings.  This script decodes each PLT entry
  add  ip, pc, #rot-imm
  add  ip, ip, #rot-imm
  ldr  pc, [ip, #off]!
then looks the GOT slot up in .rel.plt.

Usage: pltmap.py <elf> [stub-addr ...]
"""
import struct, sys


def pltmap(path):
    d = open(path, 'rb').read()
    e_shoff = struct.unpack_from('<I', d, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 0x2e)[0:3]
    so = e_shoff + shstrndx * shentsize
    strt = struct.unpack_from('<I', d, so + 16)[0]
    secs = {}
    for i in range(shnum):
        o = e_shoff + i * shentsize
        nm, typ, fl, addr, off, size, link, info = struct.unpack_from('<IIIIIIII', d, o)[0:8]
        name = d[strt + nm:d.index(b'\0', strt + nm)].decode()
        secs[name] = dict(addr=addr, off=off, size=size)
    ds, dy, rel, plt = secs['.dynsym'], secs['.dynstr'], secs['.rel.plt'], secs['.plt']
    relmap = {}
    for i in range(rel['size'] // 8):
        off, info = struct.unpack_from('<II', d, rel['off'] + i * 8)
        nm = struct.unpack_from('<I', d, ds['off'] + (info >> 8) * 16)[0]
        relmap[off] = d[dy['off'] + nm:d.index(b'\0', dy['off'] + nm)].decode()

    def ror(w):                       # ARM imm12 = ror2(rrrr)
        r = 2 * ((w >> 8) & 0xf)
        i = w & 0xff
        return ((i >> r) | (i << (32 - r))) & 0xffffffff if r else i

    out, a, end = {}, plt['addr'], plt['addr'] + plt['size']
    while a + 12 <= end:
        w1, w2, w3 = [struct.unpack_from('<I', d, a + 4 * i)[0] for i in range(3)]
        if ((w1 >> 16) & 0xfff == 0x28f and (w1 >> 12) & 0xf == 0xc      # add ip,pc,#
                and (w2 >> 16) & 0xfff == 0x28c and (w2 >> 12) & 0xf == 0xc  # add ip,ip,#
                and (w3 >> 24) & 0xf == 5 and (w3 >> 16) & 0xf == 0xc
                and (w3 >> 12) & 0xf == 0xf):                            # ldr pc,[ip,#off]!
            ip = (a + 8) + ror(w1) + ror(w2)
            off = w3 & 0xfff
            if not (w3 >> 21) & 1:
                off = -off
            out[a] = relmap.get(ip + off, '?got%x' % (ip + off))
            a += 12
            continue
        a += 2
    return out


if __name__ == '__main__':
    m = pltmap(sys.argv[1])
    if len(sys.argv) > 2:
        for t in sys.argv[2:]:
            print(t, '->', m.get(int(t, 16)))
    else:
        for k, v in sorted(m.items()):
            print('%x %s' % (k, v))
