#!/usr/bin/env python3
"""P4: 文件系统头/分区头里的 6157/664 扫描 + AV-CAM.BIN 两版数据偏移差 + 段区间表 + a10/appli 对应关系。"""
import mmap, os, struct, zlib

V = {'2.00': '/tmp/dec200.bin', '2.03': '/tmp/dec203.bin'}
MM = {}
for v, p in V.items():
    f = open(p, 'rb')
    MM[v] = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

A3 = {'2.00': 0x10431a00, '2.03': 0x10f32600}
A3LEN = {'2.00': 30290944, '2.03': 30292992}

# 1) FS 头里搜 6157/664（u16 LE/BE），对象: 各 dump 的 boot sector(512B)/ext2 superblock(1024..1152)/group desc
DUMPS = {'a1': 'work/l1-camera/nflasha1.bin', 'a2': 'work/l2-camera/nflasha2.bin',
         'a3': 'work/l1_v/nflasha3.bin', 'a4': 'work/l2-camera/nflasha4.bin',
         'a6': 'work/l2-camera/nflasha6.bin', 'a7': 'work/l1-camera/nflasha7.bin',
         'a10': 'work/l2-camera/nflasha10.bin', 'a13': 'work/l2-camera/nflasha13.bin',
         'a15': 'work/l2-camera/nflasha15.bin', 'a23': 'work/l2-camera/nflasha23.bin',
         'a1_203': 'work/v203/nflasha1_203.bin'}
TARGETS = {6157: '6157', 664: '664'}
print('== FS 头/引导区/超级块 u16/u32 LE+BE 扫描 6157/664 ==')
for lab, dp in DUMPS.items():
    if not os.path.exists(dp):
        continue
    D = open(dp, 'rb').read(4096)
    hits = []
    for off in range(0, 4090):
        for sz, fmt in ((2, '<H'), (2, '>H')):
            val = struct.unpack_from(fmt, D, off)[0]
            if val in TARGETS:
                hits.append((off, f'u16{fmt[0]}', TARGETS[val]))
        if off + 4 <= len(D):
            for fmt in ('<I', '>I'):
                val = struct.unpack_from(fmt, D, off)[0]
                if val in TARGETS:
                    hits.append((off, f'u32{fmt[0]}', TARGETS[val]))
    print(f'  {lab} ({dp}): {hits if hits else "无"}')

# 2) AV-CAM.BIN: FAT 解析（boot sector @ member start），拿起始簇 -> 明文数据偏移
def fat_info(mm, base):
    b = mm[base:base + 512]
    bs = struct.unpack_from('<H', b, 11)[0]           # bytes/sector
    spc = b[13]                                        # sectors/cluster
    resv = struct.unpack_from('<H', b, 14)[0]
    nfat = b[16]
    rootent = struct.unpack_from('<H', b, 17)[0]
    tot = struct.unpack_from('<H', b, 19)[0] or struct.unpack_from('<I', b, 32)[0]
    spf = struct.unpack_from('<H', b, 22)[0] or struct.unpack_from('<I', b, 36)[0]
    root_dir = base + (resv + nfat * spf) * bs
    data = base + (resv + nfat * spf + ((rootent * 32 + bs - 1) // bs)) * bs
    return dict(bs=bs, spc=spc, resv=resv, nfat=nfat, rootent=rootent, tot=tot, spf=spf,
                root_dir=root_dir, data=data,
                free16=struct.unpack_from('<H', b, 0x0e)[0], hdsec=struct.unpack_from('<H', b, 0x1c)[0],
                med=b[21], volid=b[0x27:0x2b].hex(), label=b[0x2b:0x36].rstrip(b'\0'),
                fsid=b[0x36:0x44].rstrip(b'\0'))


print('\n== AV-CAM.BIN 定位（FAT 目录项 -> 簇 -> 明文偏移）==')
AV = {}
for v in V:
    mm = MM[v]
    i = mm.find(b'AV-CAM  BIN', A3[v], A3[v] + A3LEN[v])
    ent = mm[i:i + 32]
    lo = struct.unpack_from('<H', ent, 26)[0]
    hi = struct.unpack_from('<H', ent, 20)[0]
    clus = (hi << 16) | lo
    sz = struct.unpack_from('<I', ent, 28)[0]
    fi = fat_info(mm, A3[v])
    doff = fi['data'] + (clus - 2) * fi['bs'] * fi['spc']
    AV[v] = (doff, sz, clus, i)
    bps = {kk: (fi[kk].hex() if isinstance(fi[kk], bytes) else fi[kk]) for kk in fi}
    print(f'  {v}: a3 member@{A3[v]:#x} BPB={bps}')
    print(f'    目录项@{i:#x} 起始簇={clus} 大小={sz} -> AV-CAM.BIN 数据 @plain {doff:#x} (a3 成员+{doff-A3[v]:#x}) '
          f'头16B={mm[doff:doff+16].hex(" ")}')
if AV['2.00'][1] == AV['2.03'][1]:
    print(f'  两版 AV-CAM.BIN 数据偏移差 = {AV["2.03"][0]-AV["2.00"][0]:#x} ({AV["2.03"][0]-AV["2.00"][0]})，文件大小相同={AV["2.00"][1]}')
else:
    print(f'  两版文件大小不同: {AV["2.00"][1]} vs {AV["2.03"][1]}；数据偏移 {AV["2.00"][0]:#x} vs {AV["2.03"][0]:#x}')

# 两版 AV-CAM 内容相同前缀/后缀 + 内容窗口偏移差（看 LUT +0x1004）
d0, s0 = AV['2.00'][:2]
d1, s1 = AV['2.03'][:2]
m0, m1 = MM['2.00'], MM['2.03']
same = 0
while same < min(s0, s1) and m0[d0 + same:d0 + same + 65536] == m1[d1 + same:d1 + same + 65536]:
    same += 65536
print(f'  AV-CAM 两版公共前缀={same} B (差异起点 {same:#x})')
# 用 2.00 的若干窗口在 2.03 a3 成员里找，测偏移差
lo1, hi1 = A3['2.03'], A3['2.03'] + A3LEN['2.03']
for fo in (0x100000, 0x400000, 0x800000, 0x84b400, 0x100, 0x2000):
    w = m0[d0 + fo:d0 + fo + 256]
    j = m1.find(w, lo1, hi1)
    print(f'  窗口 AV-CAM(2.00)+{fo:#x} -> 2.03 a3 内 {("命中 "+hex(j)+" (差 "+hex(j-(d1+fo))+")") if j>=0 else "未命中"}')

# 3) 段区间表
print('\n== tar 顶层段区间（明文偏移）==')
for v in V:
    print(f'  -- {v} --')
    secs = {}
    for line in open(f'work/fdat-body/tarmembers_{v.replace(".","")}.tsv'):
        d, sz, ty, nm = line.rstrip('\n').split('\t')
        d, sz = int(d), int(sz or 0)
        if ty != '0':
            continue
        sec = nm.split('/')[0]
        a, b = secs.get(sec, (d, d + sz))
        secs[sec] = (min(a, d), max(b, d + sz))
    for sec in sorted(secs):
        a, b = secs[sec]
        print(f'    {sec:24s} plain [{a:#011x} .. {b:#011x})  = [{a:#x}+{b-a:#x}]')

# 4) appli vs a10: kikilog / ulogio 成员与 a10 dump 对齐
print('\n== a10 内容（kikilog 等）与 0800_appli 成员对齐 ==')
for line in open('work/fdat-body/tarmembers_203.tsv'):
    d, sz, ty, nm = line.rstrip('\n').split('\t')
    if 'kikilog' in nm or 'ulogio' in nm:
        d, sz = int(d), int(sz or 0)
        print(f'  2.03 {nm} @{d:#x} len={sz}')
# kikilog.dat: a10 dump 里找它的内容
D10 = open('work/l2-camera/nflasha10.bin', 'rb').read()
d, s = None, None
for line in open('work/fdat-body/tarmembers_203.tsv'):
    dd, sz, ty, nm = line.rstrip('\n').split('\t')
    if 'kikilog' in nm:
        d, s = int(dd), int(sz or 0)
if d:
    seg = MM['2.03'][d:d + 512]
    j = D10.find(seg)
    print(f'  kikilog.dat 成员头512B 在 a10 dump 偏移: {hex(j) if j>=0 else "未命中"}  (即 a10+{hex(j)} ↔ plain+{hex(d)})' if j >= 0 else '  未命中')
    # 2.00 里 nflasha10 +1MiB 假象成员
    w = D10[1 << 20:(1 << 20) + 512]
    j = MM['2.00'].find(w)
    print(f'  a10+0x100000 窗口在 2.00 明文: {hex(j) if j>=0 else "无"}')
