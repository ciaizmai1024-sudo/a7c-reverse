import re, sys
ko = open('emmc.ko','rb').read()
str_base = 0x1f0c0
str_end = str_base + 0x944b
cur = None
targets = {}
for line in open('emmc_rela.txt'):
    m = re.match(r"Relocation section '\.(\S+?)'", line)
    if m:
        cur = '.' + m.group(1)
        continue
    m = re.match(r'([0-9a-f]{8})\s+[0-9a-f]{8}\s+R_ARM_ABS32\s+0+\s+\.rodata\.str1\.1\s*$', line)
    if not m or cur != '.text':
        continue
    off = int(m.group(1), 16)
    foff = 0x34 + off
    val = int.from_bytes(ko[foff:foff+4], 'little')
    if str_base <= val < str_end:
        s = ko[val:str(val+100)].split(b'\x00')[0].decode('latin1')
        targets[off] = (val - str_base, s)
    #print(hex(off), val-str_base, s)
keys = [k for k in sorted(targets)
        if any(w in targets[k][1] for w in ('partition table','ptbl','ALFReD','partitions','nflasha','PMBP','partinf'))]
for k in keys:
    off, s = targets[k]
    print(hex(k), hex(off), s)
