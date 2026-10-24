#!/usr/bin/env python3
"""capstone Thumb2 disassembler with literal-pool / PLT-symbol / PC-relative-string annotation.

usage: disasm.py <elf> <lo> <hi> [<pltmap.json>]
Output: one instruction per line: addr mnemonic ops  ;annotations
"""
import struct, sys, re, json
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB


def parse(f):
    d = open(f, 'rb').read()
    shoff, = struct.unpack('<I', d[0x20:0x24])
    shentsize, = struct.unpack('<H', d[0x2e:0x30])
    shnum, = struct.unpack('<H', d[0x30:0x32])
    shstrndx, = struct.unpack('<H', d[0x32:0x34])
    raw = []
    for i in range(shnum):
        e = d[shoff + i * shentsize: shoff + (i + 1) * shentsize]
        (name, typ, flags, addr, off, size, link, info, align, ent) = struct.unpack('<IIIIIIIIII', e[:40])
        raw.append(dict(name=name, off=off, size=size, addr=addr, typ=typ, link=link, ent=ent))
    stroff = raw[shstrndx]['off']
    for s in raw:
        s['nm'] = d[stroff + s['name']:d.index(b'\0', stroff + s['name'])].decode('latin1')
    return d, raw


def main():
    f = sys.argv[1]
    lo = int(sys.argv[2], 0)
    hi = int(sys.argv[3], 0)
    pltmap = {int(k, 16): v for k, v in json.load(open(sys.argv[4])).items()} if len(sys.argv) > 4 else {}
    d, S = parse(f)

    def sect(va):
        for s in S:
            if s['typ'] == 8:
                continue
            if s['addr'] <= va < s['addr'] + s['size']:
                return s
        return None

    def read32(va):
        s = sect(va)
        if not s:
            return None
        o = s['off'] + va - s['addr']
        if o + 4 > s['off'] + s['size']:
            return None
        return struct.unpack('<I', d[o:o + 4])[0]

    def cstr(va, maxlen=90):
        s = sect(va)
        if not s:
            return None
        raw = d[s['off'] + va - s['addr']:]
        j = raw.find(b'\0')
        b = raw[:min(j if j >= 0 else maxlen, maxlen)]
        if len(b) >= 3 and all(32 <= c < 127 for c in b):
            return b.decode('latin1')
        return None

    syms = {}
    for sn in ('.dynsym', '.symtab'):
        s = next((x for x in S if x['nm'] == sn), None)
        if not s:
            continue
        st = S[s['link']]
        for i in range(s['size'] // 16):
            o = s['off'] + i * 16
            nm, info, other, shndx, val, sz = struct.unpack('<IBBHII', d[o:o + 16])
            if val:
                name = d[st['off'] + nm:d.index(b'\0', st['off'] + nm)].decode('latin1')
                syms.setdefault(val & ~1, name)
    t = next(x for x in S if x['nm'] == '.text')
    localdef = {a: n for a, n in syms.items() if t['addr'] <= a < t['addr'] + t['size']}
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    def dis_all(buf, base):
        off = 0
        while off < len(buf):
            n = 0
            for i in md.disasm(buf[off:], base + off):
                n += 1
                off += i.size
                yield i
            if n == 0:
                off += 2

    hist = []   # (reg, literal value) for the PC-pool idiom  ldr rN,[pc,#..] ; add rN,pc
    for i in dis_all(d[t['off']:t['off'] + t['size']], t['addr']):
        if not (lo <= i.address < hi):
            continue
        ops = i.op_str
        note = ''
        m = re.search(r'\[pc,\s*#(0x[0-9a-f]+)\]', ops)
        if m:
            lit = ((i.address + 4) & ~3) + int(m.group(1), 16)
            v = read32(lit)
            if v is not None:
                st_ = cstr(v)
                note = '  ;lit@%#x=%#x' % (lit, v) + (('  "%s"' % st_) if st_ else '')
                if v in pltmap:
                    note += '  GOT->%s' % pltmap[v]
                if v in localdef:
                    note += '  &%s' % localdef[v]
                elif st_ is None:
                    s2 = cstr(v, 24)
                    if s2:
                        note += '  str:"%s"' % s2
        # ldr rN,[pc,#X] followed by  add rN,pc   -> rN = string/data address
        mreg = re.match(r'^(r[0-9]{1,2}|r[sl]|ip|lr),\s*\[pc,\s*#(0x[0-9a-f]+)\]$', ops)
        if i.mnemonic == 'add':
            m2 = re.match(r'^(r[0-9]{1,2}|r[sl]|ip|lr),\s*pc$', ops)
            if m2:
                reg = m2.group(1)
                for prev_reg, val in reversed(hist[-16:]):
                    if prev_reg == reg and val is not None:
                        tgt = val + ((i.address + 4) & ~3)
                        st_ = cstr(tgt)
                        note = '  ;pcrel -> %#x %s' % (tgt, ('"%s"' % st_) if st_ else '')
                        break
            m3 = re.match(r'^r[0-9]{1,2},\s*pc,\s*#(0x[0-9a-f]+|\d+)$', ops)
            if m3:
                tgt = ((i.address + 4) & ~3) + int(m3.group(1), 0)
                st_ = cstr(tgt)
                if st_:
                    note = '  ;pcrel -> %#x "%s"' % (tgt, st_)
        if i.mnemonic in ('bl', 'blx', 'b', 'bx') and ops.startswith('#'):
            tgt = int(ops[1:], 0)
            if tgt in pltmap:
                note = '  ;PLT:%s' % pltmap[tgt]
            elif tgt in localdef:
                note = '  ;->%s' % localdef[tgt]
        hist.append((mreg.group(1), read32(((i.address + 4) & ~3) + int(mreg.group(2), 16))) if mreg else (None, None))
        if len(hist) > 20:
            hist.pop(0)
        sym = localdef.get(i.address)
        print('%08x  %-8s %-34s%s%s' % (i.address, i.mnemonic, ops, note, ('   <== %s' % sym) if sym else ''))


main()
