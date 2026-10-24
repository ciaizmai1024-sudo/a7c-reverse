#!/usr/bin/env python3
"""A-scan: who instantiates / calls what inside libsdfileinputupdaterapi.so,
and which lib-name strings are dlopen'd (DllHandler::Open args).

Usage:
  a_scan.py xref  <elf> ADDR [ADDR...]     # in-.text bl/b callers of addr(s) + literal pools
  a_scan.py calls <elf>                    # list all bl targets inside .text (summary)
  a_scan.py dl  <elf>                      # find DllHandler::Open/GetSymbol call sites + arg strings
"""
import sys, struct, re
sys.path.insert(0, '.')
from elib import ELF
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB


def text_sections(e):
    out = []
    for s in e.shlist:
        if s['name'] == '.text' or (s['flags'] & 0x60000006) == 0x60000006 and s['type'] == 1:
            out.append(s)
    return out


def disasm_all(e):
    """yield (addr, insn) over all executable sections, thumb mode (this fw is all THUMB)."""
    for s in text_sections(e):
        p = e.v2p(s['addr'])
        raw = e.d[p:p + s['size']]
        cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        cs.detail = True
        for i in cs.disasm(raw, s['addr'] | 1):
            yield i


def targets(e):
    tbl = {}
    for i in disasm_all(e):
        if i.mnemonic in ('bl', 'blx', 'b', 'b.w') and i.op_str.startswith('#'):
            try:
                t = int(i.op_str.lstrip('#'), 0)
            except ValueError:
                continue
            tbl.setdefault(t, []).append(i.address)
    return tbl


def pools_to(e, v):
    """absolute word pointers to v anywhere in file"""
    out = []
    for s in e.shlist:
        if s['type'] not in (1, 8, 0xe, 0xf, 0x11) or s['type'] == 8 and False:
            pass
        p, size = s['off'], s['size']
        d = e.d[p:p + size]
        for off in range(0, size - 3, 4):
            if struct.unpack_from('<I', d, off)[0] == v:
                out.append((s['name'], e.p2v(p + off)))
    return out


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    e = ELF(path)
    T = targets(e)
    if cmd == 'xref':
        for a in sys.argv[3:]:
            v = int(a, 16)
            cl = T.get(v, []) + T.get(v | 1, [])
            print('%s callers(%#x) = %s' % (path.split('/')[-1], v, [hex(x) for x in cl]))
            print('   pools: %s' % pools_to(e, v))
    elif cmd == 'dl':
        # PLT stubs for DllHandler::Open / GetSymbol
        for nm in ('_ZN7Updater10DllHandler4OpenEPKci', '_ZN7Updater10DllHandler9GetSymbolEPKc'):
            st = e.plt_of.get(nm)
            print(nm, 'stub', hex(st) if st else None)
            if st:
                for c in T.get(st, []):
                    print('   caller %#x  sym=%s' % (c, e.sym_at(c)))
    elif cmd == 'calls':
        syms = {s['addr'] | 1: s['name'] for s in e.syms if s['addr']}
        for t, cl in sorted(T.items()):
            if t in syms and len(cl) > 1:
                print('%08x %-60s n=%d' % (t, syms[t][:60], len(cl)))


main()
