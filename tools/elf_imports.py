#!/usr/bin/env python3
"""ARM32 ELF：把 PLT 跳板地址、GOT 重定位和导入符号名对上（strip 过的 .so 也能用）。
用法：python3 tools/elf_imports.py a.so [b.so ...]
"""
import struct, sys

def parse(path):
    d = open(path, 'rb').read()
    if d[:4] != b'\x7fELF':
        print(path, '不是 ELF'); return
    e_machine = struct.unpack_from('<H', d, 18)[0]
    e_shoff = struct.unpack_from('<I', d, 32)[0]
    ses, shn, sx = struct.unpack_from('<HHH', d, 46)
    S = []
    for i in range(shn):
        o = e_shoff + i * ses
        nm, ty, fl, va, off, size, link, info, al, ent = struct.unpack_from('<IIIIIIIIII', d, o)
        S.append(dict(nmoff=nm, ty=ty, va=va, off=off, size=size, link=link, info=info))
    if not S:
        print(path, '无节头（完全 strip？）'); return
    so = S[sx]['off'] if sx < len(S) else 0

    def sname(x):
        p = so + x
        return d[p:d.index(b'\0', p)].decode('latin1') if p < len(d) else '?'
    secs = {}
    for s in S:
        secs.setdefault(sname(s['nmoff']), s)
    print('== %s  (e_machine=%d, %d 字节)' % (path, e_machine, len(d)))
    ds, dstr = secs.get('.dynsym'), secs.get('.dynstr')
    if not ds or not dstr:
        print('   没有 .dynsym/.dynstr'); return
    base = dstr['off']

    def sym(i):
        o = ds['off'] + i * 16
        name, val, size, info, other, shndx = struct.unpack_from('<IIIBBH', d, o)
        p = base + name
        n = d[p:d.index(b'\0', p)].decode('latin1') if name else ''
        return n, val, size, info, shndx
    names = [sym(i) for i in range(ds['size'] // 16)]

    # PLT：ARM/Thumb2 每个 entry 12 字节，第 0 个是 resolver；其余按 .rel.plt 顺序一一对应
    plt = secs.get('.plt')
    rp = secs.get('.rel.plt')
    if plt and rp:
        ent = 12
        print('   PLT 跳板（.plt va=%x size=%x）:' % (plt['va'], plt['size']))
        n = rp['size'] // 8
        for k in range(n):
            o = rp['off'] + k * 8
            roff, rinfo = struct.unpack_from('<II', d, o)
            nm = names[rinfo >> 8][0]
            print('     stub=%08x  GOT=%08x  → %s' % (plt['va'] + ent * (k + 1), roff, nm))
    rd = secs.get('.rel.dyn')
    if rd:
        print('   数据重定位（.rel.dyn）:')
        rows = []
        for k in range(rd['size'] // 8):
            o = rd['off'] + k * 8
            roff, rinfo = struct.unpack_from('<II', d, o)
            nm = names[rinfo >> 8][0]
            rows.append((roff, rinfo & 0xff, nm))
        for roff, typ, nm in sorted(rows):
            if nm:
                print('     GOT/数据 %08x  type=%d  → %s' % (roff, typ, nm))
    # 未定义符号一览（便于反查"它需要什么能力"）
    und = [x[0] for x in names if x[4] == 0 and x[0]]
    print('   未定义符号 %d 个: %s' % (len(und), ' '.join(sorted(und))))


for p in sys.argv[1:]:
    parse(p)
    print()
