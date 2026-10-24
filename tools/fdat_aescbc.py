#!/usr/bin/env python3
"""A7C(CXD90045) FDAT 完整解密/重打包验证 —— 密钥全部公开可得。

结构（对照 ma1co/fwtool.py fwtool/sony/fdat.py 的 AesCbcCrypter，实测确认）：
  DAT 容器: 89 55 46 55 0d0a1a0a + [u32be size]['TYPE'][data]* + [u32be 4]['DEND'][u32be crc32(覆盖[0,size-12))]
  FDAT 数据 = N 个 1024B 加密块 + 272B 尾部
      尾部前 16B = AES-CBC 的 IV
      块 0: 前 512B 用 key_aes(ECB, 平台公开 key)，后 512B 用 key_cxd90045(CBC, IV 起链)
      块 1..N: 全部 key_cxd90045(CBC, 续链)
      每个明文块 = [u16le 校验和][u16le len|bit15=末块][负载][0xFF 填充到 1020]
  解出的 FDAT 明文开头 = 'UDTRFIRM' 头（含 model/region/version + CRC32 + 文件系统等字段）

密钥:
  key_aes          = E3B0C442 98FC1C14 9AFBF4C8 996FB924   (= SHA256("") 前 16B；= libupdatertalk.so KeyArray[0:16])
  key_cxd90045     = C1AA8F7C 46341FFE D15589FC 8170A6BB 5925E85F 6282D7F9 5BA3FDF5 D303E06B (fwtool constants.py)

用法: python3 tools/fdat_aescbc.py <in.dat> <out.bin> [--pack <in.bin> <out.dat>]
"""
import sys, struct, subprocess, zlib

KEY_AES = 'e3b0c44298fc1c149afbf4c8996fb924'
KEY_90045 = 'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'

def aes(data, *enc_args):
    args = ['openssl', 'enc', *enc_args, '-nopad']
    p = subprocess.run(args, input=data, capture_output=True)
    if p.returncode:
        raise SystemExit(p.stderr.decode())
    return p.stdout

def dat_records(path):
    B = open(path, 'rb').read()
    assert B[:8] == b'\x89UFU\r\n\x1a\n', B[:8]
    out, o = [], 8
    while o + 8 <= len(B):
        n = struct.unpack('>I', B[o:o + 4])[0]
        t = B[o + 4:o + 8]
        out.append((t, o + 8, n))
        o += 8 + n
    return out, B

def unpack_frames(dec, tail):
    """dec: 已解密的块流；返回 (明文流, 块数, 校验通过数, 校验失败数)"""
    plain = bytearray()
    ok = bad = nblk = 0
    i = 0
    while i + 1024 <= len(dec):
        fr = dec[i:i + 1024]
        cs, se = struct.unpack('<HH', fr[:4])
        ln, last = se & 0x0fff, (se >> 15) & 1
        s = sum(struct.unpack('<511H', fr[2:2 + 1022])) & 0xffff
        ok, bad = (ok + 1, bad) if s == cs else (ok, bad + 1)
        plain += fr[4:4 + ln]
        nblk += 1
        i += 1024
        if last:
            break
    return bytes(plain), nblk, ok, bad

def decrypt_fdat(path):
    recs, B = dat_records(path)
    dstart = next(o for t, o, n in recs if t == b'FDAT')
    dend = next(o for t, o, n in recs if t == b'DEND')
    data = B[dstart:dend - 8]
    body, tail = data[:-0x110], data[-0x110:]
    iv = tail[:16].hex()
    head512 = aes(body[:512], '-d', '-aes-128-ecb', '-K', KEY_AES)
    rest = aes(body[512:512 + ((len(body) - 512) // 16) * 16], '-d', '-aes-256-cbc',
               '-K', KEY_90045, '-iv', iv)
    dec = head512 + rest
    plain, nblk, ok, bad = unpack_frames(dec, tail)
    print(f'FDAT 数据 {len(data)} B = {len(data)//1024} 块 + {len(tail)} B 尾部   IV={iv}')
    print(f'块头校验: 通过 {ok} / 失败 {bad}（共处理 {nblk} 块）')
    print(f'明文流 {len(plain)} B；开头: {plain[:16]!r}')
    # FdatHeader 解析（对照 fwtool）
    h = plain[:0x200]
    print('magic', h[:8], 'ver', h[8:12], 'crc32字段', h[12:16].hex())
    print('0x10起:', h[0x10:0x70].hex(' '))
    return plain, tail

if __name__ == '__main__':
    src = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else None
    plain, tail = decrypt_fdat(src)
    if outp:
        open(outp, 'wb').write(plain)
        print('写出', outp, len(plain), 'B')
