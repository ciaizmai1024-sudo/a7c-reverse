#!/usr/bin/env python3
"""libInfraSKD.so 反汇编：定位 0xFFFF5000 / 0xF340F000 的引用点并把周围代码打出来。
用法：python3 tools/skd_dis.py [so 路径] [聚焦的文件偏移] [上下文指令数]
"""
import sys
from capstone import *
from capstone.arm import *

PATH = sys.argv[1] if len(sys.argv) > 1 else 'work/l1-camera/a1_initrd/usr/lib/libInfraSKD.so'
FOCUS = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xcd0
NCTX = int(sys.argv[3]) if len(sys.argv) > 3 else 90

d = open(PATH, 'rb').read()
import struct
e_flags = struct.unpack_from('<I', d, 36)[0]
e_machine = struct.unpack_from('<H', d, 18)[0]
print('e_machine=%d e_flags=0x%08x  (bit0x%08x => %s)' % (
    e_machine, e_flags, 0x400, 'Thumb' if e_flags & 0x400 else 'ARM'))

CODE_LO, CODE_HI = 0x0, 0x2014          # 第一个 LOAD 段（filesz）
mode = CS_MODE_THUMB if (e_flags & 0x400) or (e_flags & 0x200) else CS_MODE_ARM
md = Cs(CS_ARCH_ARM, mode)
md.detail = True
md.skipdata = True

ins = []
for i in md.disasm(d[CODE_LO:CODE_HI], CODE_LO):
    ins.append(i)
print('反汇编指令数:', len(ins), '模式', 'THUMB' if mode == CS_MODE_THUMB else 'ARM')

# 找引用字面量池目标地址的指令（capstone 会给出 [pc, #imm]，手工算目标）
targets = {}
for idx, i in enumerate(ins):
    if '[' in i.op_str and 'pc' in i.op_str:
        try:
            imm = int(i.op_str.split('#')[-1].rstrip(']'), 16)
        except Exception:
            continue
        base = (i.address + 4) & ~3
        lit = base + imm
        targets.setdefault(lit, []).append(idx)
for lit in (0xcd8, 0xcdc, 0xce0):
    print('字面量 %04x 被引用于:' % lit, [hex(ins[j].address) for j in targets.get(lit, [])])

lo = max(0, min(range(len(ins)), key=lambda k: abs(ins[k].address - FOCUS)) - NCTX // 3)
print('\n=== 从 %s 起 %d 条 ===' % (hex(ins[lo].address), NCTX))
for i in ins[lo:lo + NCTX]:
    tag = ''
    print('%08x  %-24s %s %s%s' % (i.address, i.bytes.hex(' '), i.mnemonic, i.op_str, tag))
