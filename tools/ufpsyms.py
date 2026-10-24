#!/usr/bin/env python3
"""libupdaterufp.so 的 ELF 元信息转储：段表 / .dynsym / .rel.plt(->PLT 桩) / .rel.dyn(->GOT/全局) / .rodata 字符串。
用法: python3 tools/ufpsyms.py <elf>
"""
import sys, struct
sys.path.insert(0, __import__('os').path.dirname(__file__))
from ufpdis import ELF

p = sys.argv[1]
e = ELF(p)
print('== 段表 ==')
print(f'{"idx":3s} {"name":16s} {"type":6s} {"flags":6s} {"vaddr":10s} {"off":8s} {"size":8s} {"entsz":5s}')
TYP = {0: 'NULL', 1: 'PROGBITS', 2: 'SYMTAB', 3: 'STRTAB', 4: 'RELA', 6: 'REL', 14: 'DYNAMIC',
       0x6ffffffe: 'HASH', 0x6fffffff: 'VERSYM', 0x6ffffffc: 'VERNEED', 0x6ffffffd: 'VERDEF',
       0x70000003: 'ARM_ATTR', 0x70000001: 'ARM_EXIDX', 0x70000002: 'ARM_EXTAB'}
for i, s in enumerate(e.sh):
    nm, typ, fl, va, off, sz, link, info, al, es = s
    print(f'{i:3d} {e.shname[i]:16s} {TYP.get(typ,hex(typ)):6s} {fl:08x} {va:#010x} {off:#08x} {sz:#08x} {es:5d}')
print('\n== 程序头 ==')
for t in e.ph:
    print(' '.join(f'{x:#x}' for x in t))

dstr = e.sec('.dynstr')
def sn(i):
    o = dstr[4] + i
    return e.B[o:e.B.index(b'\0', o)].decode('latin1')
dsym = e.sec('.dynsym')
print('\n== .dynsym ==')
print('idx name bind type shndx value size')
for i in range(dsym[5] // (dsym[9] or 16)):
    o = dsym[4] + i * 16
    nm, val, sz, info, other, shx = struct.unpack_from('<IIIHBB', e.B, o)
    B_={0:'LOCAL',1:'GLOBAL',2:'WEAK',10:'FUNC?',11:'?',12:'?',14:'?',8:'?',9:'?',5:'?',6:'?',4:'?',3:'?',2:'?'}
    print(f'{i:3d} {sn(nm):26s} bind={info>>4:2d} type={info&0xf:2d} shndx={shx:4d} value={val:#010x} size={sz:#08x}')
def symname(idx):
    nmv = struct.unpack_from('<I', e.B, dsym[4] + idx * (dsym[9] or 16))[0]
    return sn(nmv)
print('\n== .rel.plt  (顺序 = PLT 桩顺序, 桩 = .plt+0x14+12*i) ==')
rp = e.sec('.rel.plt')
for i in range(rp[5] // 8):
    off, info = struct.unpack_from('<II', e.B, rp[4] + i * 8)
    print(f'{i:3d} GOT槽={off:#08x} 桩={0xe98+0x14+i*12:#08x} sym={symname(info>>8):26s} type={info&0xff}')
print('\n== .rel.dyn ==')
rd = e.sec('.rel.dyn')
for i in range(rd[5] // 8):
    off, info = struct.unpack_from('<II', e.B, rd[4] + i * 8)
    print(f'{i:3d} 位置={off:#08x} sym={symname(info>>8):26s} type={info&0xff} 现值={e.rd(off):#010x}')
print('\n== .got 内容 ==')
g = e.sec('.got')
for k in range(0, g[5], 4):
    v = e.rd(g[3] + k)
    print(f'{g[3]+k:#08x}: {v:#010x}')
print('\n== .rodata 字符串 (含偏移) ==')
r = e.sec('.rodata')
raw = e.B[r[4]:r[4] + r[5]]
pos = 0
for part in raw.split(b'\0'):
    if part:
        print(f'{r[3]+pos:#08x}: {part!r}')
    pos += len(part) + 1
print('\n== .data / .init_array / .fini_array ==')
for nm in ('.data', '.init_array', '.fini_array', '.data.rel.ro'):
    s = e.sec(nm)
    if s:
        for k in range(0, s[5], 4):
            print(f'{nm} {s[3]+k:#08x}: {e.rd(s[3]+k):#010x}')
