import sys
ko = open('emmc.ko', 'rb').read()
name = sys.argv[1].encode()
i = ko.find(name)
print('file off', hex(i), 'str off', hex(i - 0x1f0c0) if i >= 0 else None)
off = i - 0x19fa8  # .rodata base
for line in open('rodataxrefs.txt'):
    parts = line.split(None, 2)
    if len(parts) < 2:
        continue
    a, v = parts[0], parts[1]
    if int(v, 16) == off:
        print('xref at .text', a)
