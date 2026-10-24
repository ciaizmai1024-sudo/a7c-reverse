#!/usr/bin/env python3
"""Linear (skipdata) disassembly of a range in an ELF, with literal-pool resolution.

Usage: linsweep.py <elf> <vaddr_start> <size> <vaddr_minus_paddr_delta> [--plt mapfile] [--syms symfile]
  mapfile lines: "<vaddr>:<name>"  (PLT stubs / GOT targets)
  symfile lines: "<vaddr> <name>"  (r2 afl output or `r2 -qc 'aaa;afl'`)
"""
import sys, struct, re
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

path = sys.argv[1]
start = int(sys.argv[2], 0)
size = int(sys.argv[3], 0)
delta = int(sys.argv[4], 0)
argv = sys.argv[5:]
plt, syms, strs = {}, {}, {}
i = 0
while i < len(argv):
    if argv[i] == '--plt':
        for line in open(argv[i+1]):
            line = line.strip()
            if not line: continue
            a, n = line.rsplit(':', 1)
            plt[int(a, 0)] = n
        i += 2
    elif argv[i] == '--syms':
        for line in open(argv[i+1]):
            p = line.split()
            if p and p[0].startswith('0x'):
                syms[int(p[0], 0)] = ' '.join(p[3:]) or p[1]
        i += 2
    elif argv[i] == '--vt':
        for line in open(argv[i+1]):
            p = line.split()
            if len(p) >= 2:
                syms[int(p[0], 0)] = 'vtable<' + p[1] + '>'
        i += 2
    elif argv[i] == '--strs':
        for line in open(argv[i+1]):
            p = line.split(None, 7)
            if len(p) >= 8 and p[0].isdigit():
                try:
                    strs[int(p[2], 16)] = p[7]
                except ValueError:
                    pass
        i += 2
    else:
        i += 1

d = open(path, 'rb').read()

def rd32(v):
    return struct.unpack_from('<I', d, v - delta)[0]

def label(v):
    if v in plt: return f"IMPORT {plt[v]}"
    if v in syms: return f"FUNC {syms[v]}"
    if v in strs: return f'STR "{strs[v]}"'
    return None

code = d[start - delta: start - delta + size]
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

for ins in md.disasm(code, start):
    txt = f"{ins.address:08x}  {ins.bytes.hex():<8}  {ins.mnemonic} {ins.op_str}".rstrip()
    notes = []
    if ins.mnemonic in ('bl', 'blx') and ins.op_str.lstrip('#').startswith('0x'):
        t = int(ins.op_str.lstrip('#'), 0)
        lbl = label(t)
        if lbl: notes.append(f"  ; ==> {lbl}")
    if ins.mnemonic.startswith('ldr') and '[pc' in ins.op_str:
        try:
            m = re.search(r'\[pc, #(0x[0-9a-f]+|\d+)\]', ins.op_str)
            disp = int(m.group(1), 0)
            eff = ((ins.address + 4) & ~3) + disp
            val = rd32(eff)
            lbl = label(val)
            notes.append(f"  ; lit@{eff:#08x} = {val:#08x}" + (f"  ==> {lbl}" if lbl else ""))
        except Exception:
            pass
    print(txt + ''.join(notes))
