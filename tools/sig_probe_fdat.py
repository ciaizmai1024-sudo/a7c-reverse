#!/usr/bin/env python3
"""官方 FirmwareData_*.dat（UFU/FDAT 容器）结构走链 + RSA 验签范围穷举（离线，不碰相机）。

容器实测结构：
  0x00  8 B 容器 magic = 89 'U' 'F' 'U' 0d 0a 1a 0a        （PNG 式签名）
  0x08  记录链，每条 = [BE u32 size][4 字符 TYPE][payload size]，游标 += 8+size
        见到的 TYPE 例：DATV, PROV, FDAT, ..., DEND
  流末  = [BE u32 CRC32][00000004]['DEND'][payload 4B]     （共 16 B）
        CRC 覆盖 [0, filesize-12)（CrcChecker@0xae60）
  DEND 之前 272 B = 16 B IV + 256 B 高熵 blob（熵≈7.2）→ 本脚本验它是不是 RSA-2048 签名

用法:
  python3 tools/sig_probe_fdat.py <in.dat> [--key PEM] [--dec DECRYPTED.bin] [--walk-only] [--maxcand N]
"""
import sys, os, struct, mmap, hashlib, math, zlib, collections, subprocess, tempfile, argparse, itertools

CONT_MAGIC = b'\x89UFU\r\n\x1a\n'
TAIL = 0x110
SIGLEN = 0x100
KEY90045 = 'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'


def ent(b):
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def walk(mm):
    n = len(mm)
    assert bytes(mm[:8]) == CONT_MAGIC, '不是 UFU 容器: %s' % bytes(mm[:8]).hex()
    o, recs = 8, []
    while o + 8 <= n:
        size = struct.unpack_from('>I', mm, o)[0]
        typ = bytes(mm[o + 4:o + 8])
        if size > n - o - 8:
            break
        recs.append((o, typ, size))
        if typ == b'DEND':
            break
        o += 8 + size
    return recs


def rsa_verify(pubpem, msg_paths, sig, dgst):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.sig') as f:
        f.write(sig)
        sp = f.name
    ok = []
    try:
        for mp, tag in msg_paths:
            r = subprocess.run(['openssl', 'dgst', '-' + dgst, '-verify', pubpem,
                                '-signature', sp, mp], capture_output=True, text=True)
            ok.append((tag, r.returncode == 0 and 'Verified OK' in (r.stdout or ''), (r.stderr or '').strip()[:60]))
    finally:
        os.unlink(sp)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dat')
    ap.add_argument('--key', default='work/l1-camera/a1_initrd/etc/VerificationKey.pem')
    ap.add_argument('--dec', help='对应的解密流（full_dec*.bin），作为“解密后消息”候选')
    ap.add_argument('--walk-only', action='store_true')
    ap.add_argument('--maxcand', type=int, default=24)
    a = ap.parse_args()

    f = open(a.dat, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    n = len(mm)
    print('== %s  size=%d (%.1f MiB)  magic=%s' % (os.path.basename(a.dat), n, n / 1048576, bytes(mm[:8])))
    recs = walk(mm)
    print('== 记录链 %d 条：' % len(recs))
    for o, typ, size in recs:
        p = mm[o + 8:o + 8 + size]
        print('   @%#010x %-5s size=%12d (%8.2f MiB) 头16B=%s 熵(前4K)=%.2f'
              % (o, typ.decode('latin1'), size, size / 1048576, bytes(p[:16]).hex(), ent(bytes(p[:4096]))))
    # DEND 记录 = [BE size=4]['DEND'][payload=BE crc32[0,n-12)] 共 12 B；FDAT payload 结束于 DEND 头
    crc_at = n - 12
    print('   流末: CRC32@%#x=%08x  zlib.crc32[0,n-12)=%08x  match=%s'
          % (crc_at, struct.unpack_from('>I', mm, crc_at)[0],
             zlib.crc32(mm[:n - 12]) & 0xffffffff,
             struct.unpack_from('>I', mm, crc_at)[0] == (zlib.crc32(mm[:n - 12]) & 0xffffffff)))
    if a.walk_only:
        return

    blob_at = crc_at - TAIL          # 272 B（IV+256）起点
    iv, sig = bytes(mm[blob_at:blob_at + 16]), bytes(mm[blob_at + 16:blob_at + TAIL])
    print('== 尾 blob: IV=%s  sig[0:16]=%s  sig 熵=%.2f  sig 首字节=%02x%02x (PKCS#1 v1.5 期望 00 01/00 02)'
          % (iv.hex(), sig[:16].hex(), ent(sig), sig[0], sig[1]))

    # 候选消息：不同起/止边界（单位：相对 blob 起点的偏移）
    starts = {'file0': 0, 'cont8': 8, 'fdatrec+8': None, 'fdathdr512': None}
    msgs = []
    tmp = []
    def mkpath(bs, tag):
        p = tempfile.mktemp(suffix='.msg')
        with open(p, 'wb') as w:
            w.write(bs)
        tmp.append(p)
        msgs.append((p, tag))
    for typ, o, size in [(t, o, s) for o, t, s in recs if t in (b'FDAT', b'DATV', b'PROV')]:
        p0 = o + 8
        mkpath(bytes(mm[p0:blob_at]), '%s@%#x[..blob)' % (typ.decode(), p0))
        mkpath(bytes(mm[p0 + 0x200:blob_at]), '%s@%#x+0x200[..blob)' % (typ.decode(), p0))
        mkpath(bytes(mm[p0:p0 + size - TAIL]), '%s[..size-0x110)' % typ.decode())
        mkpath(bytes(mm[p0:p0 + size - SIGLEN]), '%s[..size-0x100)' % typ.decode())
    mkpath(bytes(mm[8:blob_at]), 'cont8[..blob)')
    mkpath(bytes(mm[0:blob_at]), 'file0[..blob)')
    mkpath(bytes(mm[8:blob_at - 16]), 'cont8[..blob-16)')
    if a.dec:
        with open(a.dec, 'rb') as g:
            dd = g.read()
        nz = max(i for i, b in enumerate(dd[-4096:]) if b) + len(dd) - 4096
        mkpath(dd[:nz + 1], 'dec[..lastNZ)')
        mkpath(dd[0x200:nz + 1], 'dec[0x200..lastNZ)')
        mkpath(dd[:len(dd) - 256], 'dec[:-256)')
        mkpath(dd[:len(dd) - 272], 'dec[:-272)')
        mkpath(dd[0x200:len(dd) - 272], 'dec[0x200:-272)')
    msgs = msgs[:a.maxcand]
    print('== 穷举 %d 组消息 × {sha256,sha1}，签名 = 尾 blob 后 256 B' % len(msgs))
    hit = False
    for d in ('sha256', 'sha1'):
        for tag, ok, err in rsa_verify(a.key, msgs, sig, d):
            print('   %-4s %-34s -> %s %s' % (d, tag, 'OK★' if ok else 'fail', err if (err and not ok) else ''))
            hit = hit or ok
    for p in tmp:
        os.unlink(p)
    print('== 命中: %s' % hit)
    # 顺带：blob 用 key_cxd90045 AES-256-CBC（IV=blob 自带 16B）解一下，看是不是"加密的摘要/密钥包装"
    try:
        from Crypto.Cipher import AES
        pt = AES.new(bytes.fromhex('c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'), AES.MODE_CBC, iv).decrypt(sig)
        print('== blob AES256CBC(key_cxd90045, IV=blob[:16]) 解出前 32 B = %s  末 16 B = %s  熵=%.2f'
              % (pt[:32].hex(), pt[-16:].hex(), ent(pt)))
    except Exception as e:
        print('== (跳过 AES：需要 pycryptodome: %s)' % e)


if __name__ == '__main__':
    main()
