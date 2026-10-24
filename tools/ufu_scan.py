#!/usr/bin/env python3
"""FirmwareData_*.dat 的外层容器 = IFF/PNG 风格的 "UFU" 分块（本轮实测出来，之前一直当成"头+帧"看）。

实测（ILCE-7C V2.00，346,206,712 B）：
  0x00000000  magic 89 55 46 55 0d 0a 1a 0a        ("\x89UFU\r\n\x1a\n"，PNG 同款思路)
  0x00000008  chunk len=4   type='DATV'  data=01 00 00 00        数据格式版本
  0x00000014  chunk len=4   type='PROV'  data=01 00 00 00        provider
  0x00000020  chunk len=172 type='UDID'                          21 条 (flag,u16 pid,u16 0x054c) —— 这固件认的 USB ID 表
  0x000000d4  chunk len=346,206,480 type='FDAT'                  载荷（里面才是 512B 头 + 帧 + 272B 尾）
  0x14a2b1ec  chunk len=4   type='DEND'  data=aa aa 81 b8        crc32(前面所有字节)【实测 == zlib.crc32(dat[:-12])】
分块记录本身：`len(BE u32) + type(4B) + data`（PNG 布局，没有每块的 CRC 字段）。

⇒ 整个 .dat 里能算的完整性只有 **DEND 的 crc32**（没有摘要/签名 chunk）；
   唯一的"非 CRC 材料" = FDAT chunk 末尾那 272 B（含 16 B CBC IV，IV 在尾区内）+ UDID 表。

用法：python3 tools/ufu_scan.py <FirmwareData_*.dat> [--hexdump UDID]
"""
import struct
import sys
import zlib


def chunks(path):
    B = open(path, 'rb').read()
    n = len(B)
    print(f'{path}  {n} B ({n/1048576:.1f} MB)')
    print(f'  magic {B[:8].hex()}  {"✓ UFU" if B[:8] == bytes.fromhex("895546550d0a1a0a") else "✗ 不是 UFU"}')
    off = 8
    recs = []
    while off + 8 <= n:
        ln = struct.unpack_from('>I', B, off)[0]
        typ = B[off + 4:off + 8]
        if ln > n:
            print(f'  !! chunk {typ!r} len={ln} 越界')
            break
        recs.append((off, ln, typ))
        data = B[off + 8:off + 8 + ln]
        extra = ''
        if typ in (b'DATV', b'PROV'):
            extra = f'data={data.hex()}'
        elif typ == b'DEND':
            calc = zlib.crc32(B[:off + 8 + ln - 4]) & 0xFFFFFFFF
            stored = struct.unpack_from('>I', B, off + 8)[0]
            extra = (f'crc 存储={stored:#010x} 实算 crc32(前面全部)={calc:#010x} '
                     f'{"✓" if calc == stored else "✗"}')
        elif typ == b'UDID':
            cnt = struct.unpack_from('>I', data, 0)[0]
            ids = []
            for i in range(cnt):
                p = 4 + i * 8
                if p + 8 > len(data):
                    break
                flag = struct.unpack_from('<I', data, p)[0]
                pid = struct.unpack_from('>HH', data, p + 4)
                ids.append(f'{pid[1]:04x}:{pid[0]:04x}(f{flag})')
            extra = f'条数={cnt}  ' + ' '.join(ids)
        print(f'  chunk @ {off:#011x}  len={ln:>12}  type={typ.decode("latin1")!r}  {extra}')
        if '--hexdump' in sys.argv and sys.argv[sys.argv.index('--hexdump') + 1:][:1] == ['UDID'] and typ == b'UDID':
            for i in range(0, min(len(data), 256), 16):
                print('    ' + f'{i:#04x}  ' + ' '.join(f'{c:02x}' for c in data[i:i + 16]))
        off += 8 + ln
        if typ == b'DEND':
            break
    print(f'  遍历止于 {off:#x}，文件长 {n:#x}  {"✓ 正好收尾" if off == n else "✗ 有多余字节"}')
    return recs


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    chunks(sys.argv[1])


if __name__ == '__main__':
    main()
