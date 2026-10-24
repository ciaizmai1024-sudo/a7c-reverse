#!/usr/bin/env python3
"""找「更新模式字母 / 模式编号」的比较点（静态，不改文件）。

FDAT 明文头（对照 fwtool FdatHeader）:
  +0x00 'UDTRFIRM'  +0x08 crc32(明文[12:512]) u32le  +0x0c '0100'
  +0x10 modeType(1)  'U'=USER(3) 'M'=MINOR(5) 'O'=VERSKIP(7) 'P'=PRODUCT(1)
  +0x14 luwFlag(1) 'N'
  +0x20 minor(u8) +0x21 major(u8) +0x24 model +0x28 region +0x30 firmwareOffset ...

做法：反汇编 .text（Thumb2），列出所有引用这些立即数的指令，并给上下文 + 最近符号名。
用法: python3 tools/modescan.py <elf.so> [额外立即数, 如 0x142 0x140]
"""
import sys, re, struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

LETTERS = {0x55: "'U' USER", 0x4f: "'O' VERSKIP", 0x4d: "'M' MINOR", 0x50: "'P' PRODUCT",
           0x4e: "'N' luwFlag", 0x33: "'3'", 0x35: "'5'", 0x37: "'7'", 0x31: "'1'"}
MODES = {1: 'PRODUCT', 2: 'LOADER_UPDATER', 3: 'USER', 4: 'SERVICE', 5: 'MINOR', 6: 'MSCRYPT', 7: 'VERSKIP'}


def parse(f):
    d = open(f, 'rb').read()
    # ELF32: e_shoff@0x20, e_shentsize@0x2e, e_shnum@0x30, e_shstrndx@0x32
    shoff, = struct.unpack('<I', d[0x20:0x24])
    shentsize, = struct.unpack('<H', d[0x2e:0x30])
    shnum, = struct.unpack('<H', d[0x30:0x32])
    shstrndx, = struct.unpack('<H', d[0x32:0x34])
    raw = []
    for i in range(shnum):
        e = d[shoff + i * shentsize: shoff + (i + 1) * shentsize]
        name, typ, flags, addr, off, size = struct.unpack('<IIIIII', e[:24])
        raw.append((name, off, size, addr))
    stroff = raw[shstrndx][1]
    secs = []
    for name, off, size, addr in raw:
        nm = d[stroff + name: d.index(b'\0', stroff + name)]
        secs.append((nm, off, size, addr))
    strtab = next((s for s in secs if s[0] == b'.strtab'), None)
    symtab = next((s for s in secs if s[0] == b'.symtab'), None)
    syms = {}
    if symtab and strtab:
        for i in range(symtab[2] // 16):
            e = d[symtab[1] + i * 16: symtab[1] + i * 16 + 16]
            st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack('<IBBHII', e)
            if st_value:
                s = d[strtab[1] + st_name: d.index(b'\0', strtab[1] + st_name)].decode('latin1')
                syms.setdefault(st_value & ~1, s)
    return secs, syms


def main():
    f = sys.argv[1]
    want = dict(LETTERS)
    rng = None
    for a in sys.argv[2:]:
        if a.startswith('--range='):
            lo, hi = a.split('=', 1)[1].split('-')
            rng = (int(lo, 0), int(hi, 0))
            continue
        v = int(a, 0)
        want[v] = MODES.get(v, 'extra')
    secs, syms = parse(f)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    for nm, off, size, addr in secs:
        if nm != b'.text':
            continue
        ins = list(md.disasm(d := open(f, 'rb').read()[off:off + size], addr | 1))
        idx = {i.address: k for k, i in enumerate(ins)}
        if rng:
            print(f'== {f} .text 区间反汇编 {rng[0]:#x}..{rng[1]:#x}')
            for x in ins:
                if rng[0] <= x.address <= rng[1]:
                    s = syms.get(x.address & ~1, '')
                    print(f'   {x.address:#08x}: {x.mnemonic:8s} {x.op_str:36s}{("  ; " + s) if s else ""}')
            return
        hits = []
        for i in ins:
            # 只看真正的立即数（排除 [pc,#0x50] 这类内存偏移）
            for imm in re.findall(r'#(?:0x)?([0-9a-fA-F]+)', re.sub(r'\[[^]]*\]', '', i.op_str)):
                v = int(imm, 16)
                if v in want:
                    hits.append((i.address, i.mnemonic + ' ' + i.op_str, want[v]))
                    break
        print(f'== {f} .text @{addr:#x} size={size:#x}: {len(hits)} 命中')
        shown = set()
        for a, txt, lbl in hits:
            k = idx[a]
            lo, hi = max(0, k - 6), min(len(ins), k + 4)
            key = (lo, hi)
            if key in shown:
                continue
            shown.add(key)
            print(f'--- {a:#x}: {txt}   <-- {lbl}')
            for x in ins[lo:hi]:
                s = syms.get(x.address & ~1, '')
                mark = ' <<<' if x.address == a else '    '
                print(f'  {mark} {x.address:#08x}: {x.mnemonic:8s} {x.op_str:36s}{("  ; " + s) if s else ""}')


main()
