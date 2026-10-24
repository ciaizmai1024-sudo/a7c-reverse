#!/usr/bin/env python3
"""ARM32 ELF (ET_EXEC, vaddr!=off) analysis helper: PLT map, exidx function list,
precise BL call-site scan per function (mode from exidx thumb bit)."""
import struct, sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN


def load(path):
    d = open(path, 'rb').read()
    phoff, shoff = struct.unpack_from('<II', d, 0x1c)
    phent, phnum, shent, shnum, shstr = struct.unpack_from('<HHHHH', d, 0x2a)
    strtab = struct.unpack_from('<I', d, shoff + shstr * shent + 16)[0]
    secs = {}
    for i in range(shnum):
        o = shoff + i * shent
        nm, typ, fl, addr, off, size = struct.unpack_from('<IIIIII', d, o)[0:6]
        name = d[strtab + nm:d.index(b'\0', strtab + nm)].decode()
        secs[name] = (addr, off, size)
    segs = [struct.unpack_from('<IIIIIIII', d, phoff + i * phent) for i in range(phnum)]

    def v2o(v):
        for typ, off, va, pa, fsz, msz, fl, al in segs:
            if typ == 1 and va <= v < va + fsz:
                return off + (v - va)
    return d, secs, segs, v2o


def dynsyms(d, secs):
    ds, dy = secs['.dynsym'], secs['.dynstr']
    out = {}
    for i in range(ds[2] // 16):
        b = ds[1] + i * 16
        nmoff, val, size, info = struct.unpack_from('<IIII', d, b)
        if nmoff:
            out[i] = (d[dy[1] + nmoff:d.index(b'\0', dy[1] + nmoff)].decode(), val, info)
    return out


def reltab(d, secs, syms):
    res = {}
    for s in ('.rel.plt', '.rel.dyn'):
        if s not in secs:
            continue
        a, o, sz = secs[s]
        for i in range(sz // 8):
            off, info = struct.unpack_from('<II', d, o + i * 8)
            si = info >> 8
            res[off] = (syms.get(si, ('?', 0, 0))[0], s)
    return res


def ror(v):
    r = 2 * ((v >> 8) & 0xf)
    i = v & 0xff
    return ((i >> r) | (i << (32 - r))) & 0xffffffff if r else i


def pltmap(d, secs, v2o, relmap):
    pa, po, ps = secs['.plt']
    out, rev = {}, {}
    a = pa
    while a + 12 <= pa + ps:
        o = v2o(a)
        if o is None:
            break
        w1, w2, w3 = [struct.unpack_from('<I', d, o + 4 * i)[0] for i in range(3)]
        if ((w1 >> 16) & 0xfff == 0x28f and (w1 >> 12) & 0xf == 0xc
                and (w2 >> 16) & 0xfff == 0x28c and (w2 >> 12) & 0xf == 0xc
                and (w3 >> 24) & 0xf == 5 and (w3 >> 16) & 0xf == 0xc
                and (w3 >> 12) & 0xf == 0xf):
            base = (a + 8) + ror(w1) + ror(w2)
            off = w3 & 0xfff   # LDR imm12 is a plain 12-bit offset (not rotated)
            nm = relmap.get(base + off, ('?got%x' % (base + off),))[0]
            out[a] = nm
            rev[nm] = a
            a += 4
            continue
        a += 4
    return out, rev


def uleb(d, o):
    r = s = 0
    while True:
        b = d[o]
        o += 1
        r |= (b & 0x7f) << s
        s += 7
        if not b & 0x80:
            break
    return r, o


def functions(d, secs):
    """exidx: returns list of (start_vaddr, thumb_bool)."""
    a, o, sz = secs['.ARM.exidx']
    out = []
    for i in range(sz // 8):
        pre, idx = struct.unpack_from('<II', d, o + i * 8)
        f1, _ = uleb(d, o + i * 8)
        thumb = bool(f1 & 0x80000000)
        v = (f1 & 0x7fffffff) + a   # FDE-relative to .ARM.exidx base addr
        out.append((v, thumb))
    return sorted(set(out))


def callsites(path, targets_names=None, targets=None):
    d, secs, segs, v2o = load(path)
    syms = dynsyms(d, secs)
    relmap = reltab(d, secs, syms)
    pm, rev = pltmap(d, secs, v2o, relmap)
    names = targets_names or list(rev)
    T = {}
    for n in names:
        if n in rev:
            T[rev[n]] = n
    fns = functions(d, secs)
    ta, to, ts = secs['.text']
    ends = [fns[i + 1][0] for i in range(len(fns) - 1)] + [ta + ts]
    res = {}
    for (st, th), en in zip(fns, ends):
        if st < ta or st >= ta + ts:
            continue
        mode = CS_MODE_THUMB if th else CS_MODE_ARM
        md = Cs(CS_ARCH_ARM, CS_MODE_LITTLE_ENDIAN | mode)
        md.detail = True
        o = v2o(st)
        code = d[o:o + (en - st) + 8]
        for ins in md.disasm(code, st | (1 if th else 0)):
            if ins.mnemonic in ('bl', 'blx') and ins.address >= en:
                break
            if ins.address >= en:
                break
            if ins.mnemonic in ('bl', 'blx'):
                try:
                    t = int(ins.insn_size and ins.op_str.lstrip('#+'), 0)
                except Exception:
                    continue
                if t in T:
                    res.setdefault(T[t], []).append((ins.address, th, ins.bytes.hex(), ins.mnemonic))
    return pm, rev, res


if __name__ == '__main__':
    path = sys.argv[1]
    want = sys.argv[2:]
    pm, rev, res = callsites(path, want or None)
    print('== %s ==' % path)
    print('PLT stubs total: %d' % len(pm))
    for w in want:
        print('%-24s stub=%s calls=%s' % (w, hex(rev[w]) if w in rev else 'NOSTUB', len(res.get(w, []))))
        for a, th, b, mn in res.get(w, []):
            print('    %s @ %08x (%s) bytes=%s' % (mn, a, 'T' if th else 'A', b))
