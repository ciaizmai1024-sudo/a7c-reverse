#!/usr/bin/env python3
"""adjtbl.py — 打印 Jiritsu 两代共用的两张表（可复查 notes/jiritsu.md 的结论）

用法:
  python3 tools/adjtbl.py sym   <libJiritsu.so>     # .dynsym 里“有定义”的函数+大小（权威函数边界）
  python3 tools/adjtbl.py adj   <adjstctl.elf>      # 命令描述符表 {chan, qid, name}（19 条, stride 0x48）
  python3 tools/adjtbl.py areas <libJiritsu.so>     # .data.rel.ro 的 34 条 {id, 调参文件路径}
注: 本 ELF 的 .dynsym 字段为非标准排布 nm,val,sz,[info,other,shndx(2B)]。
"""
import struct, sys

def syms(p):
    B = open(p, 'rb').read()
    secs = sections(B)
    dynsym, dynstr = secs['.dynsym'][3], secs['.dynstr'][3]
    out = []
    for i in range(secs['.dynsym'][4]//16):
        nm, val, sz = struct.unpack('<3I', B[dynsym+i*16: dynsym+i*16+12])
        info, other, shndx = B[dynsym+i*16+12], B[dynsym+i*16+13], struct.unpack('<H', B[dynsym+i*16+14:][0:2])[0]
        if nm == 0 and shndx == 0 and i > 0x200: break
        if not shndx: continue
        e = B.index(b'\0', dynstr+nm); n = B[dynstr+nm:e].decode('latin1')
        if n: out.append((val & ~1, sz, val & 1, n))
    for v, s, t, n in sorted(out):
        print(f'{v:#07x} size={s:#05x} {"THUMB" if t else "ARM "} {n}')

def adj(p):
    B = open(p, 'rb').read()
    i = B.find(b'JIRITSU_MODE')
    if i < 0: print('no table'); return
    start = i
    for k in range(19):
        nm = start + 0x48*k
        e = B.index(b'\0', nm); name = B[nm:e].decode('latin1')
        qid, chan = struct.unpack('<2I', B[nm-8:nm])
        pw = (chan >> 16) & 0xffff
        print(f'cmd={pw&0xff:3d} pfunc={pw>>8:#04x} chan_lo={chan&0xffff:#06x} qid={qid:#x}  {name}')

def sections(B):
    shoff = struct.unpack('<I', B[0x20:0x24])[0]
    shentsize, shnum, shstrndx = struct.unpack('<HHH', B[0x2e:0x34])
    strtab = struct.unpack('<I', B[shoff+shstrndx*shentsize+16: shoff+shstrndx*shentsize+20])[0]
    out = {}
    for i in range(shnum):
        s = B[shoff+i*shentsize:][:40]
        no, typ, flags, addr, off, size = struct.unpack('<IIIIII', s[:24])
        e = B.index(b'\0', strtab+no)
        out[B[strtab+no:e].decode()] = (typ, flags, addr, off, size)
    return out

def areas(p):
    B = open(p, 'rb').read()
    off = sections(B)['.data.rel.ro'][3]
    for i in range(34):
        a, b = struct.unpack('<2I', B[off+i*8: off+i*8+8])
        e = B.index(b'\0', b)
        print(f'{a:#05x} {B[b:e].decode()}')

if __name__ == '__main__':
    cmd, path = sys.argv[1], sys.argv[2]
    {'sym': syms, 'adj': adj, 'areas': areas}[cmd](path)
