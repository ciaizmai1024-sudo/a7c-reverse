#!/usr/bin/env python3
"""用 vendored fwtool 把 updater body cramfs 解到目录，并输出 manifest(path,size,sha256)。
用法: python3 work/v203/dump_body.py <img> <outdir>  （在 a7creverse 仓库根运行）"""
import sys, os, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'refs', 'fwtool.py'))
from fwtool.archive import cramfs as C

img, out = sys.argv[1], sys.argv[2]
f = open(img, 'rb')
assert C.isCramfs(f)
man = []
for x in C.readCramfs(f):
    p = os.path.join(out, x.path.lstrip("/"))
    if x.contents is None:
        os.makedirs(p, exist_ok=True)
        man.append((x.path, 0, ''))
    else:
        data = bytes(x.contents.read())
        os.makedirs(os.path.dirname(p) or out, exist_ok=True)
        open(p, 'wb').write(data)
        man.append((x.path, len(data), hashlib.sha256(data).hexdigest()))
for row in man:
    print('\t'.join(map(str, row)))
