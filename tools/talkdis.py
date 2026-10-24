#!/usr/bin/env python3
"""Linear Thumb disassembly of libupdatertalk.so .text with GOT/reloc annotation."""
import sys, struct, binascii
from capstone import *

F = sys.argv[1] if len(sys.argv) > 1 else \
    '/Users/wubin/pi-cwd/sony/a7creverse/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so'
d = open(F, 'rb').read()

# section table (unused beyond notes)

# GOT/reloc table:  .rel.dyn @ paddr 0x4d8 size 0x40 ; DT_ symbols resolved by hand below
RELOCS = {  # vaddr -> symbol (from rabin2 -R, libupdatertalk.so)
    0x8804: 'AES_decrypt', 0x8808: 'AES_set_decrypt_key', 0x880c: 'memcpy',
    0x8818: 'KeyArray', 0x8820: 'decx',
}
SYMS = {  # vaddr -> name
    0x540: '_init', 0x54c: '.plt', 0x560: 'imp.AES_decrypt', 0x56c: 'imp.AES_set_decrypt_key',
    0x578: 'imp.memcpy', 0x57c: 'imp.plt(memcpy-thunk)', 0x590: 'imp.__cxa_finalize',
    0x5a4: 'entry0', 0x5bc: 'entry.fini0', 0x5fc: 'entry.init0',
    0x620: 'Dec_ScrambleInit', 0x648: 'Dec_Scramble', 0x678: '_fini',
    0x8830: 'KeyArray[32]', 0x8854: 'decx[244]',
}

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = False

start, end, off = 0x5a4, 0x678, 0x5a4
print('; ==== libupdatertalk.so  .text  0x%x..0x%x  (Thumb) ====' % (start, end))
code = d[off:end]
for ins in md.disasm(code, start):
    tag = SYMS.get(ins.address, '')
    line = '%08x  %-12s  %-8s %s' % (ins.address, binascii.hexlify(ins.bytes).decode(), ins.mnemonic, ins.op_str)
    if tag:
        line += '   ;---- %s' % tag
    # annotate pc-relative literal loads
    if ins.mnemonic == 'ldr' and '[pc,' in ins.op_str:
        try:
            delta = int(ins.op_str.split('#')[-1].rstrip(']'), 0)
        except Exception:
            delta = None
        if delta is not None:
            lit = ((ins.address + 4) & ~3) + delta
            v = struct.unpack_from('<I', d, lit)[0]
            note = ''
            if v in RELOCS:
                note = '   ==> GOT reloc slot, resolves to: %s' % RELOCS[v]
            elif 0x86d8 <= v < 0x8950:
                note = '   ==> 0x%x' % v
            line += '   ; literal pool @0x%x = 0x%08x%s' % (lit, v, note)
    print(line)

print()
print('; ==== .data (vaddr 0x882c .. 0x8850) ====')
for a in range(0x882c, 0x8850, 4):
    v = struct.unpack_from('<I', d, a - 0x8000)[0]
    print('  %08x  %08x %s' % (a, v, ('<= ' + RELOCS[a]) if a in RELOCS else ('<= KeyArray' if a == 0x8830 else '')))
print('; KeyArray bytes @0x8830 (32):', binascii.hexlify(d[0x830:0x850]).decode())
print(';   == SHA-256("") digest, byte order identical to the standard hex digest')
print('; .bss: decx @0x8854 size 244 (struct aes_key_st: rd_key[60] + rounds)')
