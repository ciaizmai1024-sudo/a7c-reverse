#!/usr/bin/env python3
"""FDAT 尾部 272 B（16 B IV + 256 B blob）到底是谁的东西 —— 离线穷举验证。

动机（notes/updater_verify.md §6 / FIRMWARE_MOD.md §3.5）：
  crypter.elf 里没找到 RSA/EVP，也没读到 0x110 这个长度；DEND 的 CRC32 覆盖 [0,size-12)
  ⇒ 尾部一定被 CRC 覆盖，但「被覆盖」不等于「被验签」。
本脚本只做离线密码学穷举，不碰相机：
  A. 结构/熵：blob 是不是看起来像 PKCS#1 v1.5 签名后的密文（高熵）、还是像明文/低熵
  B. 用已知密钥解它：
       B1 AES-256-CBC(key_cxd90045, iv=blob 自带前 16B)
       B2 AES-256-CBC(key_cxd90045, iv=FDAT 密文最后一个块)   ← CBC 链「续链」
       B3 AES-128-ECB(key_aes)  / B4 AES-256-ECB(key_cxd90045)
  C. RSA 验签穷举：包里能找到的 RSA 公钥/证书 × 若干候选消息 × 常见摘要
  D. 交叉比对（若给第二个 .dat）：尾巴是否跨文件恒定 ⇒ 密钥包装 vs 逐文件签名

用法:
  python3 tools/fdat_tail.py <in.dat> [--key PEM|CERT] [--dat2 <another.dat>]
"""
import sys, struct, subprocess, hashlib, zlib, os

KEY_AES = bytes.fromhex('e3b0c44298fc1c149afbf4c8996fb924')
KEY_90045 = bytes.fromhex('c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b')


def enc(data, *args):
    p = subprocess.run(['openssl', 'enc', *args, '-nopad'], input=data, capture_output=True)
    if p.returncode:
        return None
    return p.stdout


def records(B):
    assert B[:8] == b'\x89UFU\r\n\x1a\n', B[:8]
    out, o = [], 8
    while o + 8 <= len(B):
        n = struct.unpack('>I', B[o:o + 4])[0]
        t = B[o + 4:o + 8]
        out.append((t, o + 8, n))
        o += 8 + n
        if t == b'DEND':
            break
    return out


def ent(b):
    """粗熵：不同字节数 / 可见字符比例。"""
    from collections import Counter
    c = Counter(b)
    import math
    H = -sum(v / len(b) * math.log2(v / len(b)) for v in c.values())
    pr = sum(1 for x in b if 32 <= x < 127) / len(b)
    return H, len(c), pr


def show(tag, b):
    if b is None:
        print(f'  {tag}: (失败)')
        return
    H, nuniq, pr = ent(b)
    printable = repr(b[:48], 'latin1')
    print(f'  {tag}: len={len(b)} 熵={H:.2f}/8.0 uniq={nuniq}/256 可打印={pr:.2f}')
    print(f'     头 {b[:16].hex()}  {printable}')


def fdat_parts(B):
    recs = records(B)
    d = next(r for r in recs if r[0] == b'FDAT')
    dend = next(r for r in recs if r[0] == b'DEND')
    body = B[d[1]:dend[1] - 8]
    return body, body[:-0x110], body[-0x110:]


# ---------- C: RSA ----------
def rsa_pub(pem_or_der_path):
    """从 pem/cert 里取 (n,e)，用 openssl 输出解析。"""
    p = subprocess.run(['openssl', 'x509', '-in', pem_or_der_path, '-noout', '-pubkey'],
                       capture_output=True)
    txt = None
    if p.returncode == 0:
        txt = p.stdout
    else:
        p = subprocess.run(['openssl', 'pkey', '-pubin', '-in', pem_or_der_path, '-noout', '-text'],
                           capture_output=True)
        txt = p.stdout
    p2 = subprocess.run(['openssl', 'pkey', '-pubin', '-text', '-noout'],
                        input=txt, capture_output=True)
    s = p2.stdout.decode()
    n, e = None, None
    hexbuf = []
    for line in s.splitlines():
        if line.strip().startswith('Modulus:'):
            hexbuf = []
            mode = 'n'
        elif line.strip().startswith('Exponent:'):
            if mode == 'n':
                n = bytes.fromhex(''.join(hexbuf))
            m = line.split('(')
            e = int(m[1].split(' ')[0]) if len(m) > 1 else None
            mode = None
        elif mode == 'n' and ':' in line:
            hexbuf.append(line.strip().replace(':', ''))
    return n, e


def rsa_verify(n, e, sig, msg_hashes):
    """裸 RSA: m = sig^e mod n；打印 m 的结构（判断 PKCS#1 v1.5 + DigestInfo）。"""
    s = int.from_bytes(sig, 'big')
    if s >= n:
        return 'sig >= n（不是这个模数的签名）'
    m = pow(s, e, n)
    mb = m.to_bytes(len(n), 'big')
    DI = {
        'md5': bytes.fromhex('3020300c06082a864886f70d020505000410'),
        'sha1': bytes.fromhex('3021300906052b0e03021a05000414'),
        'sha256': bytes.fromhex('3031300d060960864801650304020105000420'),
        'sha224': bytes.fromhex('302d300d06096086480165030402040500041c'),
        'sha384': bytes.fromhex('3041300d060960864801650304020205000430'),
        'sha512': bytes.fromhex('3051300d060960864801650304020305000440'),
    }
    hits = [k for k, v in DI.items() if v in mb]
    pad = mb[0] == 0 and mb[1] == 1 and all(x == 0xff for x in mb[2:mb.rfind(b'\x00')]) and mb.rfind(b'\x00') > 2
    out = f'  m 前 8B={mb[:8].hex()} 0x01+FF 填充模式={pad} DigestInfo 命中={hits or "无"}'
    print(out)
    for algo, dg in hits:
        for name, h in msg_hashes.items():
            if hashlib.new(algo, h).digest() in mb:
                print(f'    ★匹配: DigestInfo({algo}) 对应候选消息 {name}')
    return out


def main():
    dat = sys.argv[1]
    keys = [a for a in sys.argv[2:] if a.startswith('--key')]
    dat2 = sys.argv[sys.argv.index('--dat2') + 1] if '--dat2' in sys.argv else None
    B = open(dat, 'rb').read()
    body, cipher, tail = fdat_parts(B)
    iv, blob = tail[:16], tail[16:]
    print(f'== {os.path.basename(dat)}')
    print(f'  FDAT 数据 {len(body)} B；尾 272B 在 FDAT 记录内 (record 尾)，故被 DEND CRC32 覆盖')
    dend = next(r for r in records(B) if r[0] == b'DEND')
    stored = struct.unpack('>I', B[dend[1]:dend[1] + 4])[0]
    calc = zlib.crc32(B[:dend[1]]) & 0xffffffff
    print(f'  DEND: 存 {stored:08x} 算 {calc:08x} {"✓(覆盖整文件含尾 272B)" if stored == calc else "✗"}')
    print(f'  尾 IV = {iv.hex()}')
    print('== A. 256B blob 自身统计')
    show('blob', blob)
    print('  blob 前 32B:', blob[:32].hex())
    print('  blob 末 32B:', blob[-32:].hex())
    print('  blob 是否全 0:', blob == b'\0' * 256, ' 是否为某已知字符串:', all(32 <= c < 127 for c in blob))
    print('== B. 用已知密钥解它')
    show('B1 CBC(cxd90045, iv=blob[:16])', enc(blob, '-d', '-aes-256-cbc', '-K', KEY_90045.hex(), '-iv', iv.hex()))
    show('B2 CBC(cxd90045, iv=最后密文块)', enc(blob, '-d', '-aes-256-cbc', '-K', KEY_90045.hex(), '-iv', cipher[-16:].hex()))
    show('B3 ECB(cxd90045 前16B)', enc(blob, '-d', '-aes-128-ecb', '-K', KEY_90045[:16].hex()))
    show('B4 ECB(cxd90045 后16B)', enc(blob, '-d', '-aes-128-ecb', '-K', KEY_90045[16:].hex()))
    show('B5 CBC(key_aes, iv=blob[:16])', enc(blob, '-d', '-aes-128-cbc', '-K', KEY_AES.hex(), '-iv', iv.hex()))
    # 明文流（用于 C 的候选消息）
    head512 = enc(cipher[:512], '-d', '-aes-128-ecb', '-K', KEY_AES.hex())
    rest = enc(cipher[512:512 + ((len(cipher) - 512) // 16) * 16], '-d', '-aes-256-cbc',
               '-K', KEY_90045.hex(), '-iv', iv.hex())
    dec = head512 + rest
    plain, i = bytearray(), 0
    last_blk_ct = b''
    while i + 1024 <= len(dec):
        fr = dec[i:i + 1024]
        cs, se = struct.unpack('<HH', fr[:4])
        ln, last = se & 0xfff, (se >> 15) & 1
        plain += fr[4:4 + ln]
        i += 1024
        if last:
            last_blk_ct = cipher[i - 1024:i]
            break
    print('  明文流 %d B，末块 bit15 命中=%s' % (len(plain), '是' if last_blk_ct else '否（扫完所有块也没置位）'))
    cands = {
        'FDAT 密文体(不含尾272B)': cipher[:-0x110],
        'FDAT 密文体(含尾272B)': cipher,
        '整个文件(DEND 前)': B[:dend[1]],
        '明文流': bytes(plain),
        'UDTRFIRM 头 0x200': bytes(plain[:0x200]),
        'firmware.tar (包内)': open('firmware.tar', 'rb').read() if os.path.exists('firmware.tar') else b'',
    }
    mh = {k: v for k, v in cands.items()}
    for k, v in mh.items():
        print(f'  候选消息 {k:30s} len={len(v):<12} md5={hashlib.md5(v).hexdigest()} sha256={hashlib.sha256(v).hexdigest()[:16]}')
    print('== C. RSA 穷举（包内可找到的公钥）')
    kp = [a.split('=', 1)[1] for a in sys.argv[2:] if a.startswith('--key=')]
    kp += ['firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/share/network/cert/certification.pem']
    for k in kp:
        if not os.path.exists(k):
            continue
        try:
            n, e = rsa_pub(k)
        except Exception as ex:
            print(f'  {k}: 解析失败 {ex}')
            continue
        if not n:
            print(f'  {k}: 取不到 modulus')
            continue
        print(f'  密钥 {k}: n={len(n)*8}bit e={e}')
        if len(n) == 256:
            rsa_verify(n, e, blob, mh)
        else:
            print(f'    模数 {len(n)*8} bit ≠ 2048 ⇒ 256B 不可能是它的 PKCS#1 签名（跳过）')
    if dat2:
        B2 = open(dat2, 'rb').read()
        _, c2, t2 = fdat_parts(B2)
        print('== D. 交叉比对')
        print(f'  文件2 尾 272B 与文件1 {"相同 ⇒ 更像密钥/固定包装" if t2 == tail else "不同 ⇒ 逐文件数据（签名或随机 IV+密文）"}')
        print(f'  文件2 IV={t2[:16].hex()}  blob 前 16B={t2[16:32].hex()}')


main()
