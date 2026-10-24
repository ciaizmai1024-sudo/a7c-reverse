#!/usr/bin/env python3
"""
校验 firmware.tar_unpacked 里每个 *.sum 的 CRC32 + size（对应相机里的 uc_crc32sum.elf）。

.sum 记录格式（逗号分隔，实测）：
  flag,crc32,size(16),mode,uid?,gid?,user,group,-1,-1,path,
  flag=0 普通文件；flag=5 目录（crc=ffffffff, size=0）；flag=2 符号链接（第 11 字段是目标）

用法： python3 tools/verify_sums.py [firmware.tar_unpacked]
"""
import os, sys, zlib, re

root = sys.argv[1] if len(sys.argv) > 1 else 'firmware.tar_unpacked'

def dirs(base):
    return sorted(d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d)) and re.match(r'^\d{4}_', d))

total = ok = bad = missing = 0
for d in dirs(root):
    if d.endswith('_sum'):
        continue
    # 同一组件的目录与校验目录只差 1 序号：0100_config / 0101_config_sum
    num = int(d.split('_')[0])
    sumdir = next((c for c in dirs(root)
                   if c.endswith('_sum') and int(c.split('_')[0]) == num + 1), None)
    if not sumdir:
        print(f'[{d}] 无对应 _sum 目录，跳过')
        continue
    sumfiles = [f for f in os.listdir(os.path.join(root, sumdir)) if f.endswith('.sum')]
    for sf in sumfiles:
        n_ok = n_bad = n_miss = 0
        for line in open(os.path.join(root, sumdir, sf), errors='replace'):
            f = line.rstrip('\n').split(',')
            if len(f) < 11 or f[10] in ('', '-1') or f[0] == '5':
                continue
            total += 1
            p = os.path.join(root, d, f[10])
            if not os.path.isfile(p):
                n_miss += 1; missing += 1
                continue
            data = open(p, 'rb').read()
            crc = format(zlib.crc32(data) & 0xffffffff, '08x')
            size = int(f[2], 16)
            if crc == f[1] and size == len(data):
                n_ok += 1; ok += 1
            else:
                n_bad += 1; bad += 1
                print(f'  NG {d}/{f[10]}: list crc={f[1]} size={size}  实际 crc={crc} size={len(data)}')
        print(f'{sumdir}/{sf} -> {d}: OK={n_ok} NG={n_bad} 包内缺失={n_miss}')
print(f'\n合计条目 {total}：CRC+size 相符 {ok}，不符 {bad}，包内缺失 {missing}')
print('结论：.sum 只是 CRC32 完整性校验（可重算），不含任何签名。')
