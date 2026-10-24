#!/usr/bin/env python3
"""按节头反汇编 libInfraSKD.so（Thumb），并定位 0xFFFF5000 / 0xF340F000 字面量的引用点。
用法：python3 tools/skd_dis2.py [so] [--around 0xVA] [--n 200] [--mode thumb|arm]
"""
import struct, sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

args = sys.argv[1:]
PATH = args[0] if args and not args[0].startswith('--') else 'work/l1-camera/a1_initrd/usr/lib/libInfraSKD.so'
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default
FOCUS = int(opt('--around', '0'), 0)
N = int(opt('--n', '220'))
MODE = opt('--mode', 'thumb')

d = open(PATH, 'rb').read()
e_shoff = struct.unpack_from('<I', d, 32)[0]
e_shentsize = struct.unpack_from('<H', d, 46)[0]
e_shnum = struct.unpack_from('<H', d, 48)[0]
e_shstrndx = struct.unpack_from('<H', d, 50)[0]
sh = []
so_str = None
for i in range(e_shnum):
    o = e_shoff + i * e_shentsize
    name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from('<IIIIIIIIII', d, o)
    if i == e_shstrndx:
        so_str = off
    sh.append(dict(idx=i, name=None, typ=typ, addr=addr, off=off, size=size, nameoff=name))
for s in sh:
    no = so_str + s['nameoff']
    end = d.index(b'\0', no) if b'\0' in d[no:no + 40] else no + 16
    s['name'] = d[no:end].decode('latin1')
print('节:')
for s in sh:
    print('  %-16s off=%06x addr=%08x size=%06x type=%d' % (s['name'], s['off'], s['addr'], s['size'], s['typ']))
cand = [s for s in sh if s['typ'] == 1 and s['size'] > 0x200]
text = max(cand, key=lambda s: s['size'])
print('选用代码区:', text['name'], hex(text['off']), hex(text['size']))

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if MODE == 'thumb' else CS_MODE_ARM)
md.detail = True
md.skipdata = True
base, off, size = text['addr'] or text['off'], text['off'], text['size']
ins = list(md.disasm(d[off:off + size], base))
print('反汇编 %d 条（mode=%s, base=%08x）' % (len(ins), MODE, base))

# 字面量池里的两个窗常量
LITS = {}
for pat, nm in ((struct.pack('<I', 0xF340F000), 'PA 0xF340F000(key 窗)'),
                (struct.pack('<I', 0xFFFF5000), 'PA 0xFFFF5000(1KiB 窗)')):
    i = 0
    while True:
        j = d.find(pat, i)
        if j < 0:
            break
        LITS[j] = nm
        i = j + 1
print('常量位置:', {hex(k): v for k, v in LITS.items()})

refs = {}
for idx, ins_i in enumerate(ins):
    s = ins_i.op_str
    if 'pc' not in s or '[' not in s:
        continue
    try:
        imm = int(s.split('#')[-1].rstrip(']'), 16)
    except Exception:
        continue
    for basealign in ((ins_i.address + 4) & ~3, (ins_i.address + 4) & ~2, (ins_i.address + 4)):
        if basealign in LITS:
            refs.setdefault(basealign, []).append(idx)
for lit, lst in refs.items():
    print('%s (%08x) <- %s' % (LITS[lit], lit, [hex(ins[j].address) for j in lst]))

sites = sorted({i for lst in refs.values() for i in lst})
for s0 in sites:
    lo = max(0, s0 - N // 3)
    print('\n===== %s 附近（%d 条，从 %s 起）=====' % (LITS[max(refs, key=lambda L: s0 in refs[L])], N, hex(ins[lo].address)))
    for i in ins[lo:lo + N]:
        mark = ' <<<' if i.address in [ins[x].address for x in sites] else ''
        print('%08x  %-22s %s %s%s' % (i.address, i.bytes.hex(' '), i.mnemonic, i.op_str, mark))
