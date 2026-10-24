#!/usr/bin/env python3
"""Per-function call/string summary from an annotated disassembly (work/text.asm style).

Usage: python3 work/cflow.py <annotated.asm> <syms.txt> <funcaddr-or-prefix> [...]
For each named function (bounds from .dynsym dump = syms.txt) print:
  * every bl/blx target (with the annotation from the asm line, e.g. '-> PLT sys_mount')
  * every string constant referenced (==>) and message-buffer loads ([rN,#off])
Only reads files; writes to stdout.
"""
import re, sys

asm_path, sym_path = sys.argv[1], sys.argv[2]
want = [int(x, 16) for x in sys.argv[3:]]

syms = []
for ln in open(sym_path):
    m = re.match(r'0x([0-9a-f]+) size=0x([0-9a-f]+) \w+ (\S+)', ln)
    if m:
        syms.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3)))
syms.sort()

lines = open(asm_path).read().splitlines()
pat_addr = re.compile(r'^0x([0-9a-f]{4,})\s')

def bounds(a):
    for i, (v, sz, n) in enumerate(syms):
        if v == a:
            return v, v + (sz or 0x1000), n
    raise SystemExit('sym not found: %x' % a)

for a in want:
    lo, hi, name = bounds(a)
    calls, strs, mem = [], [], []
    for ln in lines:
        m = pat_addr.match(ln)
        if not m:
            continue
        v = int(m.group(1), 16)
        if not (lo <= v < hi):
            continue
        if '->' in ln and ('bl ' in ln.split(';;')[0] or 'blx' in ln.split(';;')[0] or 'b.w' in ln.split(';;')[0] or ln.split(';;')[0].strip().startswith('b ')):
            calls.append(ln.strip())
        mm = re.search(r'==>\s*(.*)', ln)
        if mm:
            strs.append('0x%x  %s' % (v, mm.group(1)))
        mm2 = re.search(r'\[r(\d+),\s*#(0x[0-9a-f]+|\d+)\]', ln)
        if mm2 and ('ldr' in ln.split(';;')[0] or 'ldrb' in ln.split(';;')[0] or 'ldrh' in ln.split(';;')[0] or 'str' in ln.split(';;')[0]):
            mem.append('0x%x  %s' % (v, ln.strip()))
    print('==== %s @0x%x..0x%x' % (name, lo, hi))
    seen = set()
    for c in calls:
        key = re.search(r'-> .*', c).group(0)
        if key not in seen:
            seen.add(key)
            print('  CALL %s' % key)
    for s in strs:
        print('  STR  %s' % s)
    for mm in mem:
        print('  MEM  %s' % mm)
    print()
