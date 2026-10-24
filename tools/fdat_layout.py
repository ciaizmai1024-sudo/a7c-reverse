#!/usr/bin/env python3
"""UDTRFIRM 明文容器的布局读取器（已用 ILCE-7C V2.00 实测校准）。

实测结论（全部由本工具可复核）：
  明文 = [主头 512B][对象1][对象2]…（对象个数来自主头 +56）
  主头字段（小端）：
     +0   "UDTRFIRM"
     +8   u32  头 CRC32，覆盖 hdr[12:512)      （已验：0xcdf83cd7）
     +12  4B   格式串 "0100"
     +16  u8   modeType（'U'/'O'/'M'/'P'…）
     +20  u32  78(0x4e)（含义未定）
     +32  u32  0x200  头长
     +36  u32  机型码（0x91030019）  +40 region  +44 0
     +48  u32  对象2 的偏移（0x23200 = 143,872）
     +52  u32  对象2 的长度（344,709,632）
     +56  u32  对象个数（本包 = 2）
     +64  u8   'U'（对象1 的 modeType）  +68 u32 0x200  +72 u32 对象1 长度(143,360)
  对象1 = Compressed ROMFS（cramfs，magic 0x28CD3D45）= PC 自带 `updater.img`
          = 相机 `/usr/bin/udtrbody.bin`（三者逐字节相同）⇒ 更新体本身是个 cramfs 镜像
  对象2 = 裸 tar（首个成员 `0100_config/`，数字前缀 = config.xml 里的作业顺序）

用法：
  python3 tools/fdat_layout.py /tmp/fdat_dec.bin [--cmp updater.img,firmware.tar]
  （要先生成明文：python3 tools/fdat_aescbc.py <FirmwareData_*.dat> /tmp/fdat_dec.bin）
"""
import struct
import sys
import os
import zlib

CRAMFS_MAGIC = 0x28CD3D45


def parse(buf):
    if buf[:8] != b'UDTRFIRM':
        raise SystemExit('不是 UDTRFIRM 明文（先跑 tools/fdat_aescbc.py 解密）')
    hdr_crc = struct.unpack_from('<I', buf, 8)[0]
    calc = zlib.crc32(buf[12:512]) & 0xFFFFFFFF
    fields = {
        'fmt': buf[12:16].decode('latin1'),
        'modeType': chr(buf[16]),
        'u20': struct.unpack_from('<I', buf, 20)[0],
        'hdrlen': struct.unpack_from('<I', buf, 32)[0],
        'model': struct.unpack_from('<I', buf, 36)[0],
        'region': struct.unpack_from('<I', buf, 40)[0],
        'u44': struct.unpack_from('<I', buf, 44)[0],
        'obj2_off': struct.unpack_from('<I', buf, 48)[0],
        'obj2_size': struct.unpack_from('<I', buf, 52)[0],
        'nobj': struct.unpack_from('<I', buf, 56)[0],
        'obj1_mode': chr(buf[64]),
        'obj1_hdrlen': struct.unpack_from('<I', buf, 68)[0],
        'obj1_size': struct.unpack_from('<I', buf, 72)[0],
    }
    print(f'主头 512 B  fmt={fields["fmt"]!r} modeType={fields["modeType"]!r} '
          f'model={fields["model"]:#010x} region={fields["region"]} nobj={fields["nobj"]}')
    print(f'  头 CRC 存储={hdr_crc:#010x} 实算 crc32(hdr[12:512])={calc:#010x} '
          f'{"✓" if calc == hdr_crc else "✗ 不符"}')
    print(f'  对象1 长度={fields["obj1_size"]}  对象2 偏移={fields["obj2_off"]} 长度={fields["obj2_size"]}')
    total = fields['obj2_off'] + fields['obj2_size']
    print(f'  对象2 结尾={total}  明文实长={len(buf)}  {"✓" if total == len(buf) else "✗ 有多余尾巴"}')

    objs = []
    o = fields['obj1_hdrlen']                       # cramfs 紧跟主头
    end = fields['obj2_off']
    blob = buf[o:end]
    magic = struct.unpack_from('<I', blob, 0)[0] if len(blob) >= 4 else 0
    kind = 'cramfs' if magic == CRAMFS_MAGIC else '未知'
    info = ''
    if kind == 'cramfs':
        fsize, flags, future = struct.unpack_from('<III', blob, 4)
        name = blob[16:32].split(b'\0')[0].decode('latin1')
        crc, edition = struct.unpack_from('<II', blob, 32)
        shifts = struct.unpack_from('<I', blob, 40)[0]
        info = (f'fs 大小={fsize} flags={flags:#x} name={name!r} crc={crc:#010x} edition={edition} '
                f'shifts={shifts:#x} 长度{"✓" if fsize == len(blob) else "✗"}')
    objs.append((o, len(blob), kind, info))
    objs.append((fields['obj2_off'], fields['obj2_size'], 'tar',
                 '首成员=' + buf[fields['obj2_off']:fields['obj2_off'] + 100].split(b'\0')[0].decode('latin1')))
    for off, size, kind, info in objs:
        print(f'  对象 @{off:#09x} {size:>12} B  {kind}  {info}')
    return fields, objs


def cmp_local(path, objs, names):
    """把对象与本地已有副本逐字节比对（证明"我们手里已经有全部明文段"）。"""
    for nm in names:
        if not os.path.exists(nm):
            print(f'  [跳过] 本机没有 {nm}')
            continue
        want = os.path.getsize(nm)
        for off, size, kind, _ in objs:
            if size != want:
                continue
            ok = True
            done = 0
            with open(nm, 'rb') as f, open(path, 'rb') as g:
                g.seek(off)
                left = size
                while left:
                    n = min(1 << 22, left)
                    x = f.read(n)
                    y = g.read(n)
                    if x != y:
                        ok = False
                        diff = next((i for i, (u, v) in enumerate(zip(x, y)) if u != v), None)
                        print(f'    差异在 {nm} 内偏移 {(left - n + diff) if diff is not None else "长度不同"} '
                              f'（本地 {x[diff:diff+8].hex() if diff is not None else b""} vs 机身段 {y[diff:diff+8].hex() if diff is not None else b""}）')
                        break
                    left -= n
                    done += n
            print(f'  {"✓" if ok else "✗"} {nm} == 对象 @{off:#x}（{kind}）全 {done} B 逐字节')


def main():
    path = sys.argv[1]
    names = []
    for i, a in enumerate(sys.argv):
        if a == '--cmp':
            names = sys.argv[i + 1].split(',')
    buf = open(path, 'rb').read()
    fields, objs = parse(buf)
    if names:
        print('与本地副本比对：')
        cmp_local(path, objs, names)


if __name__ == '__main__':
    main()
