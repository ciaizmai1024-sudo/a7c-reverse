#!/usr/bin/env python3
"""annotated dump helper"""
import sys, elib, struct

path = sys.argv[1]
pltmap = sys.argv[2]
e = elib.ELF(path)
e.load_pltmap(pltmap)

def xref_sites(v):
    """code (thumb) that loads a literal equal to v"""
    out = []
    text = e.sec('.text')
    p = e.v2p(text['addr'])
    raw = e.d[p:p + text['size']]
    for ins in e.cs_t.disasm(raw, text['addr']):
        if ins.mnemonic == 'ldr' and ('[pc' in ins.op_str):
            import re
            m = re.search(r'\[pc,?\s*(?:#(-?0x[0-9a-f]+|-?\d+))?\]', ins.op_str)
            k = int(m.group(1), 0) if m and m.group(1) else 0
            tgt = ((ins.address + 4) & ~3) + k
            pv = e.v2p(tgt)
            if pv is not None and struct.unpack_from('<I', e.d, pv)[0] == v:
                out.append(ins.address)
    return out

cmd = sys.argv[3]
if cmd == 'x':
    for pat in sys.argv[4:]:
        for a, s in e.findstr(pat):
            print('STR %08x  %r' % (a, s[:100]))
            for c in xref_sites(a):
                print('   loaded at %08x' % c)
            # also pool words
            for secname in ('.text', '.data', '.rodata', '.init_array', '.got'):
                sc = e.sec(secname)
                if not sc:
                    continue
                raw = e.bytes_at(sc['addr'], sc['size'])
                for i in range(0, len(raw) - 3, 4):
                    if struct.unpack_from('<I', raw, i)[0] == a:
                        print('   pool %s+%x = %08x' % (secname, i, sc['addr'] + i))
elif cmd == 'd':
    for a in sys.argv[4:]:
        v = int(a, 16)
        print('=== dis %s' % hex(v))
        e.dis(v, 4096)
elif cmd == 'c':
    for nm in sys.argv[4:]:
        st = e.plt_of.get(nm)
        print('%s stub=%s' % (nm, hex(st) if st else None))
        if st:
            for c in e.callers_of(st):
                print('   called at %08x' % c)
