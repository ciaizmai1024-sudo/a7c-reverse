#!/usr/bin/env python3
"""Tiny ARM/Thumb2 disasm helper (capstone) with PLT annotation.
usage: armdis.py <elf> <start_vaddr> <n_bytes> [--arm]"""
import struct, sys, re
import capstone

def parse(p):
    d = open(p, 'rb').read()
    e_shoff = struct.unpack_from('<I', d, 0x20)[0]
    esz = struct.unpack_from('<H', d, 0x2e)[0]
    n = struct.unpack_from('<H', d, 0x30)[0]
    strx = struct.unpack_from('<H', d, 0x32)[0]
    sh = [struct.unpack_from('<10I', d, e_shoff + i*esz) for i in range(n)]
    names = {}
    for s in sh:
        nm = d[s[0]+sh[strx][4]:].split(b'\0')[0].decode()
        if nm:
            names[nm] = s
    import subprocess
    relplt = names['.rel.plt']; dynsym = names['.dynsym'][4]; dynstr = names['.dynstr'][4]
    # two common layouts: got-slot offset == stub+16+8k (ARM) or == stub+16+12k etc.
    # detect empirically using objdump-independent check: pick k where .rel.plt[0] offset,
    # try candidate deltas so that the bytes at that file offset are a PLT-style ldr sequence.
    plt = {}
    out = subprocess.run(['objdump','-d',p],capture_output=True,text=True).stdout
    cur=None
    import re as _re
    for line in out.splitlines():
        m=_re.match(r'^0*([0-9a-f]+) <(.+)@plt>:', line)
        if m: plt[int(m.group(1),16)] = m.group(2)
    return d, names, plt

def a2o(names, addr):
    for nm, s in names.items():
        if s[1] == 1 and s[3] <= addr < s[3]+s[5]:
            return s[4] + (addr - s[3]), nm
    return None, None

def main():
    p, start, nb = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0)
    arm = '--arm' in sys.argv
    d, names, plt = parse(p)
    off, sec = a2o(names, start)
    code = d[off:off+nb]
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM if arm else capstone.CS_MODE_THUMB)
    md.detail = True
    for ins in md.disasm(code, start):
        note = ''
        if ins.mnemonic.startswith('b'):
            m=re.search(r'#(0x[0-9a-f]+)', ins.op_str)
            if m:
                t=int(m.group(1),16)
                if t in plt: note='  ; -> PLT '+plt[t]
                else:
                    for base,nm in plt.items():
                        if t&~1 in (base,): note='  ; -> PLT '+nm

        print(f"{ins.address:#08x}\t{ins.bytes.hex()}\t{ins.mnemonic}\t{ins.op_str}{note}")

if __name__ == '__main__':
    main()
