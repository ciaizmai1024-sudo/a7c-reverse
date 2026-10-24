#!/usr/bin/env python3
"""robust literal-pool xref scan + full annotated thumb disassembly of .text"""
import sys, struct, re, elib

path, pltmap = sys.argv[1], sys.argv[2]
e = elib.ELF(path)
e.load_pltmap(pltmap)
text = e.sec('.text')
base = text['addr']
p = e.v2p(base)
raw = e.d[p:p + text['size']]


def lit_targets(a):
    """yield (kind, target_pool_addr) for pc-relative loads at address a"""
    hw0 = struct.unpack_from('<H', raw, a - base)[0]
    res = []
    if (hw0 & 0xF800) == 0x4800:  # ldr rt,[pc,#imm8*4]
        imm = (hw0 & 0xFF) * 4
        res.append(((a + 4) & ~3) + imm)
    elif (hw0 in (0xF8DF, 0xF8CF)) and a + 4 <= base + len(raw):
        hw1 = struct.unpack_from('<H', raw, a - base + 2)[0]
        if (hw1 & 0xF000) == 0xF000:
            imm = hw1 & 0xFFF
            res.append(((a + 4) & ~3) + (imm if hw0 == 0xF8DF else -imm))
    return res


def find_xref(val):
    out = []
    for a in range(base, base + len(raw) - 1, 2):
        for t in lit_targets(a):
            pv = e.v2p(t)
            if pv is not None and struct.unpack_from('<I', e.d, pv)[0] == val:
                out.append(a)
                break
    return out


def pool_words(val):
    out = []
    for secname in ('.text', '.data', '.rodata', '.got', '.init_array', '.ARM.extab'):
        sc = e.sec(secname)
        if not sc:
            continue
        d = e.bytes_at(sc['addr'], sc['size'])
        for i in range(0, len(d) - 3, 4):
            if struct.unpack_from('<I', d, i)[0] == val:
                out.append(sc['addr'] + i)
    return out


cmd = sys.argv[3]
if cmd == 'x':
    for pat in sys.argv[4:]:
        for a, s in e.findstr(pat):
            print('STR %08x  %r' % (a, s[:100]))
            for pw in pool_words(a):
                print('   pool %08x' % pw)
            for c in find_xref(a):
                print('   ldr@ %08x' % c)
elif cmd == 'xv':
    for v in sys.argv[4:]:
        v = int(v, 16)
        print('VAL %08x' % v)
        for pw in pool_words(v):
            print('   pool %08x' % pw)
        for c in find_xref(v):
            print('   ldr@ %08x' % c)
elif cmd == 'd':
    for a in sys.argv[4:5]:
        print('=== %s' % a)
        e.dis(int(a, 16), int(sys.argv[5], 16) if len(sys.argv) > 5 else 4096)
