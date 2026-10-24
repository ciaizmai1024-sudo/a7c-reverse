#!/usr/bin/env python3
"""只解 FDAT 的前几 MB，看 firmware.tar 开头的成员名（判断 2.03 包里有没有 0400_updater/nflasha1）。"""
import sys, struct, zlib
from Crypto.Cipher import AES
sys.path.insert(0, 'tools')
from fdat_aescbc import KEY_AES, KEY_90045, dat_records

def peek(path, nbytes=4<<20):
    recs, B = dat_records(path)
    fdat = [(t, o, n) for t, o, n in recs if t == b'FDAT']
    print('chunks:', [(t.decode('latin1'), n) for t, o, n in recs])
    t, off, n = fdat[0]
    print(f'FDAT data @{off:#x} len={n}  ({(n-272)/1024:.0f} 块 + 272 尾)')
    data = B[off:off+n]
    tail = data[n-272:]
    iv = tail[:16]
    print('IV(尾前 16B) =', iv.hex())
    K = (nbytes // 1024) + 2
    ea = AES.new(bytes.fromhex(KEY_AES), AES.MODE_ECB)
    p0a = ea.decrypt(data[:512])
    ka = AES.new(bytes.fromhex(KEY_90045), AES.MODE_CBC, iv)
    dec = ka.decrypt(data[512:512+1024*K+512])
    frames = [p0a + dec[:512]]
    d = dec[512:]
    for i in range(0, len(d) - 1023, 1024):
        frames.append(d[i:i+1024])
    plain = bytearray(); bad = 0; last = False
    for k, fr in enumerate(frames):
        cs, se = struct.unpack('<HH', fr[:4])
        ln, fl = se & 0xfff, (se >> 15) & 1
        s = sum(struct.unpack('<511H', fr[2:2+1022])) & 0xffff
        if s != cs: bad += 1
        plain += fr[4:4+ln]
        if fl: last = True; break
    print(f'帧数 {len(frames)}  校验失败 {bad}  末块标志 {last}  明文字节 {len(plain)}')
    print('明文开头:', plain[:16])
    hdr = plain[:512]
    print('头 CRC 存=%08x 实算=%08x' % (struct.unpack('<I', hdr[8:12])[0], zlib.crc32(bytes(hdr[12:512])) & 0xffffffff))
    mt, luw = hdr[16:17], hdr[20:21]
    model, region = struct.unpack('<II', hdr[36:44])
    vmi, vma = struct.unpack('<HH', hdr[32:36]) if False else (0,0)
    print(f'modeType={mt!r} luw={luw!r} model={model:#010x} region={region} 头前12={hdr[:12]!r}')
    print('对象表 +48/+52/+56 =', struct.unpack('<II', hdr[48:56]), struct.unpack('<I', hdr[56:60])[0])
    p = bytes(plain)
    for pat in (b'0100_config', b'0200_updater', b'0400_updater', b'0700_part_image', b'dev/nflasha1', b'updater', b'cram', b'SYSASTRA'):
        i = p.find(pat)
        print(f'  {pat!r}: {"命中 @" + hex(i) if i >= 0 else "未见"}')
    # tar 成员名解析
    base = p.find(b'ustar')
    print('第一个 ustar @', hex(base) if base >= 0 else '未见')
    if base > 0:
        start = base - 155
        names = []
        o = start
        for _ in range(40):
            blk = p[o:o+512]
            if len(blk) < 512 or blk[0] == 0: break
            nm = blk[:100].split(b'\0')[0].decode('latin1')
            sz = int(blk[124:136].split(b'\0')[0] or b'0', 8)
            names.append((nm, sz))
            o += 512 + ((sz + 511) // 512) * 512
            if blk[156:158] != b'ustar'[:2] and b'ustar' not in blk[150:160]: break
        for nm, sz in names[:25]:
            print(f'   tar 成员 {nm!r} size={sz}')
    open('work/v203_head.bin', 'wb').write(p)
    print('明文前段已存 work/v203_head.bin')

peek(sys.argv[1])
