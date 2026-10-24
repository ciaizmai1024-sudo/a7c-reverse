#!/usr/bin/env python3
"""A7C(FirmwareData_ILCE7CV200.dat) FDAT 去帧 + AES-128-ECB 解密 + 帧校验验证实操。

实测确认（本机）：
  DAT: magic 89 55 46 55 0d0a1a0a; 记录 DATV/PROV/UDID/FDAT; 结尾 'DEND'+BE CRC32(覆盖 [0,size-12))
  FDAT = 若干 1024B 帧（密文），每帧解密后 = [u16 校验和][u16 sizeAndEnd(bit15=末帧, bits0-11=负载长)][负载][0xFF 填充]
  AES-128-ECB, key = SHA256("")[0:16] = e3b0c44298fc1c149afbf4c8996fb924（= libupdatertalk.so 的 KeyArray 前 16 字节，编译期硬编码）
  明文首帧开头即 "UDTRFIRM"（= crypter.elf 校验的二段更新器头，头部 +8 处有 CRC32(BE)）

用法:
  python3 tools/fdat_unwrap.py <dat> [out.bin] [--frames N]
"""
import sys, struct, zlib, subprocess, os

KEY = 'e3b0c44298fc1c149afbf4c8996fb924'

def aes_ecb_decrypt(buf: bytes) -> bytes:
    p = subprocess.run(['openssl', 'enc', '-d', '-aes-128-ecb', '-nopad', '-K', KEY],
                       input=buf, capture_output=True)
    if p.returncode:
        raise SystemExit('openssl 失败: ' + p.stderr.decode())
    return p.stdout

def records(path):
    f = open(path, 'rb')
    f.seek(0, 2); size = f.tell(); f.seek(8)
    out = []
    while f.tell() < size - 16:
        n = struct.unpack('>I', f.read(4))[0]
        t = f.read(4)
        out.append((t, n, f.tell()))
        f.seek(n, 1)
        if t == b'DEND':
            break
    return out, size

def main():
    dat = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
    nmax = None
    for a in sys.argv:
        if a.startswith('--frames'):
            nmax = int(a.split('=')[1]) if '=' in a else 40
    recs, size = records(dat)
    print('== DAT 记录:')
    for t, n, o in recs:
        print(f'  {t.decode("latin1"):6s} size={n:<12} (0x{n:x})  data@0x{o:x}')
    fdat = next(r for r in recs if r[0] == b'FDAT')
    f = open(dat, 'rb'); f.seek(fdat[2])
    total = fdat[1]
    nframes, rem = divmod(total, 1024)
    print(f'== FDAT: {total} B = {nframes} 整帧 + {rem} B 尾部')

    plain = bytearray()
    ck_ok = ck_bad = 0
    first_bad = None
    frames = 0
    chunk = 256 * 1024           # 每次 256 帧
    pos = 0
    while pos < total:
        take = min(chunk, total - pos)
        take -= take % 1024
        if take == 0:
            take = total - pos                    # 尾部不足一帧的部分
        enc = f.read(take)
        if len(enc) % 16:
            enc += b'\x00' * (16 - len(enc) % 16)
        dec = aes_ecb_decrypt(enc)
        i = 0
        while i + 4 <= len(dec) and (pos + i) < total:
            fsz = min(1024, total - pos - i)
            fr = dec[i:i + fsz]
            if fsz < 1024:
                print(f'  尾部非整帧 {fsz} B @0x{fdat[2]+pos+i:x}: {fr[:32].hex()}')
                break
            cs, se = struct.unpack('<HH', fr[:4])
            ln = se & 0x0fff
            last = (se >> 15) & 1
            s = sum(struct.unpack('<511H', fr[2:2 + 511 * 2])) & 0xffff
            if s == cs:
                ck_ok += 1
            else:
                ck_bad += 1
                if first_bad is None:
                    first_bad = (pos + i, cs, s)
            plain += fr[4:4 + ln]
            frames += 1
            if last:
                print(f'  末帧标志出现在帧 #{frames} (流内偏移 0x{pos+i:x})，负载 {ln} B')
                break
            i += 1024
        pos += i if i else len(dec)
        if nmax and frames >= nmax:
            print(f'  (--frames {nmax}) 提前停止')
            break
    print(f'== 帧校验: OK={ck_ok} BAD={ck_bad}' + (f' 首个失败帧 @0x{first_bad[0]:x} 存 cs=0x{first_bad[1]:04x} 算=0x{first_bad[2]:04x}' if first_bad else ''))
    print(f'== 解出明文字节流 {len(plain)} B，前 64B:')
    print('  ' + bytes(plain[:64]).hex())
    print('  ' + repr(bytes(plain[:64]), 'latin1'))
    # 明文里找已知结构
    for tag in (b'UDTRFIRM', b'ustar', b'\x89UFU', b'ENDMARKER', b'DEND'):
        j = bytes(plain).find(tag)
        print(f'  首个 {tag!r} @ 明文偏移', hex(j) if j >= 0 else '未找到')
    if outp:
        open(outp, 'wb').write(bytes(plain))
        print('== 写出', outp)

main()
