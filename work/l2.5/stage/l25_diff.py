#!/usr/bin/env python3
"""before/after 分区镜像对比：变化扇区范围 + FAT 布局归类 + 新目录项原始 32B。"""
import struct, sys


def ranges_of(ch, sect=512):
    r = []
    for s in ch:
        if r and s == r[-1][1]:
            r[-1][1] = s + sect
        else:
            r.append([s, s + sect])
    return r


def bpb(img):
    for bo in (0, 0x600, 0x400, 0x100000):
        if img[bo + 510:bo + 512] == b'\x55\xaa' and img[bo] in (0xeb, 0xe9):
            bps = struct.unpack_from('<H', img, bo + 11)[0]
            if bps not in (512, 1024, 2048, 4096, 8192, 16384, 32768):
                continue
            d = dict(bo=bo, bps=bps, spc=img[bo + 13], rsvd=struct.unpack_from('<H', img, bo + 14)[0],
                     nfat=img[bo + 16], rootent=struct.unpack_from('<H', img, bo + 17)[0],
                     fatsz=struct.unpack_from('<H', img, bo + 21)[0],
                     hidden=struct.unpack_from('<I', img, bo + 28)[0],
                     fatsz32=struct.unpack_from('<I', img, bo + 32)[0],
                     rootcl=struct.unpack_from('<I', img, bo + 44)[0])
            fat0 = bo + (d['rsvd'] + d['hidden']) * bps
            fatsz = (d['fatsz'] or d['fatsz32']) * bps
            d['fat0'], d['fatsz'] = fat0, fatsz
            d['root0'] = fat0 + d['nfat'] * fatsz
            d['data0'] = d['root0'] + d['rootent'] * 32
            return d
    return None


def classify(off, g):
    if g is None:
        return '?'
    bo = g['bo']
    if bo <= off < bo + g['bps']:
        return 'BOOT'
    if g['fat0'] <= off < g['fat0'] + g['nfat'] * g['fatsz']:
        which = (off - g['fat0']) // g['fatsz']
        return f'FAT#{which}'
    if g['root0'] <= off < g['data0']:
        return 'ROOTDIR'
    if off >= g['data0']:
        clus = (off - g['data0']) // (g['bps'] * g['spc'])
        return f'DATA(cluster {clus})'
    return 'RESV'


def fat_changes(b, a, g, sect=512):
    if g is None:
        return
    for off in range(g['fat0'], g['fat0'] + g['nfat'] * g['fatsz'], 4):
        v1, v2 = b[off:off + 4], a[off:off + 4]
        if v1 != v2 and off < g['fat0'] + g['fatsz']:  # 只看 FAT#0
            c = (off - g['fat0']) // 4
            print(f'    FAT  entry#{c}: {v1[::-1].hex()} -> {v2[::-1].hex()}')


def find_name(img, pat):
    out, i = [], 0
    while True:
        i = img.find(pat, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def main():
    before, after, label = sys.argv[1:4]
    pats = [p.upper().encode() for p in sys.argv[4:]] or [b'ZZPROBE']
    b, a = open(before, 'rb').read(), open(after, 'rb').read()
    n = min(len(b), len(a))
    print(f'== {label}: before={len(b)} after={len(a)} B')
    g = bpb(a)
    if g:
        print(f'   BPB@0x{g["bo"]:x} bps={g["bps"]} spc={g["spc"]} rsvd={g["rsvd"]} nfat={g["nfat"]} '
              f'rootent={g["rootent"]} fatsz=0x{g["fatsz"]:x} fat0=0x{g["fat0"]:x} root0=0x{g["root0"]:x} data0=0x{g["data0"]:x}')
    else:
        print('   BPB 未找到')
    ch = [i for i in range(0, n, 512) if b[i:i + 512] != a[i:i + 512]]
    print(f'   变化扇区 {len(ch)} 个:')
    for r in ranges_of(ch):
        print(f'     0x{r[0]:08x}-0x{r[1] - 1:08x}  [{classify(r[0], g)}]')
    if g:
        fat_changes(b, a, g)
    for pat in pats:
        for i in find_name(a, pat):
            tag = 'NEW' if b[i:i + len(pat)] != pat else 'old'
            ent = (i // 32) * 32
            print(f'   name {pat!r} @0x{i:x} ({classify(ent, g)}) [{tag}] entry32@0x{ent:x}: {a[ent:ent + 32].hex()}')
            for k in range(1, 4):  # 前面的槽位（可能是 LFN / 旧首字节 0x05/删除标记）
                e2 = ent - 32 * k
                if e2 >= 0:
                    print(f'        prev[-{k}] @0x{e2:x}: {a[e2:e2 + 32].hex()}')
            break_only = None
    # 逐字节差异（前 40 处，用于人工核对）
    diffs = [i for i in range(n) if b[i] != a[i]]
    print(f'   字节级差异 {len(diffs)} 处, 前 40: ' + ' '.join(f'{i:x}:{b[i]:02x}>{a[i]:02x}' for i in diffs[:40]))


if __name__ == '__main__':
    main()
