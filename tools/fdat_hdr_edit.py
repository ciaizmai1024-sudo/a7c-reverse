#!/usr/bin/env python3
"""对 A7C 的官方 .dat 做"只改身份字段"的最小重打包（不需要私钥）。

可改的只有 FDAT 明文头里落在 **AES-128-ECB(公开 key_aes)** 覆盖区内的字段：
  payload+16 modeType('U'/'O'/'M'/'P')  +32 minor +33 major  +36 model  +40 region
（payload+508 之后属于 AES-256-CBC(key_cxd90045) 区，改动会牵动整条 CBC 链，本工具不碰）

改完必须同步三处校验（都是 CRC32，公开算法，可重算）：
  1) 头 checksum  = zlib.crc32(payload[12:512])            （实测：范围到 512，不是 400）
  2) 帧0 checksum = Σ (明文块0 偏移 2..1023 的 u16le) & 0xFFFF
  3) 外层 DEND CRC = zlib.crc32(整个文件去掉最后 12 字节)
未知/不可重算：FDAT 尾部 272B 里的 256B（疑 RSA-2048 签名）——原样搬过去。

用法:
  tools/fdat_hdr_edit.py IN.dat --prove                      # 只做往返证明（不写文件）
  tools/fdat_hdr_edit.py IN.dat --set-mode O --out OUT.dat   # 试 verskip 模式
  tools/fdat_hdr_edit.py IN.dat --set-region 1 --out OUT.dat
"""
import argparse, struct, subprocess, sys, zlib, os

KEY_AES = 'e3b0c44298fc1c149afbf4c8996fb924'                       # = SHA256("")[:16]
KEY_CXD90045 = 'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'
TAIL = 272


def ecb(buf, key, dec=True):
    cmd = ['openssl', 'enc', '-d' if dec else '-e', '-aes-128-ecb', '-nopad', '-K', key]
    return subprocess.run(cmd, input=buf, capture_output=True, check=True, timeout=120).stdout


def cbc(buf, key, iv, dec=True):
    cmd = ['openssl', 'enc', '-d' if dec else '-e', '-aes-256-cbc', '-nopad', '-K', key, '-iv', iv]
    return subprocess.run(cmd, input=buf, capture_output=True, check=True, timeout=120).stdout


def find_fdat(data):
    assert data[:8] == b'\x89UFU\r\n\x1a\n', '不是 UFU 容器'
    o = 8
    while True:
        n, = struct.unpack('>I', data[o:o + 4]); ty = data[o + 4:o + 8]
        if ty == b'FDAT':
            return o + 8, n
        if ty == b'DEND':
            raise SystemExit('没找到 FDAT 记录')
        o = o + 8 + n


def frame_cs(plain_block):
    return sum(struct.unpack('<' + 'H' * ((len(plain_block) - 2) // 2), plain_block[2:2 + ((len(plain_block) - 2) // 2) * 2])) & 0xFFFF


def main():
    import functools
    print = functools.partial(__builtins__['print'] if isinstance(__builtins__, dict) else __builtins__.print, flush=True)
    ap = argparse.ArgumentParser()
    ap.add_argument('dat')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--set-mode', choices=list('UOMP'))
    ap.add_argument('--set-region', type=lambda s: int(s, 0))
    ap.add_argument('--set-model', type=lambda s: int(s, 0))
    ap.add_argument('--set-version', help='major.minor，例如 2.00')
    ap.add_argument('--out')
    a = ap.parse_args()

    data = bytearray(open(a.dat, 'rb').read())
    off, size = find_fdat(bytes(data))
    body = bytes(data[off:off + size - TAIL])
    tail = bytes(data[off + size - TAIL:])
    iv = tail[:16].hex()
    print(f'文件 {len(data)} B；FDAT data @{off} size {size}；帧数 {len(body)//1024}')

    b0 = body[:1024]
    p_head = ecb(b0[:512], KEY_AES)            # 明文块0 前 512B（含 4B 帧头 + payload[0:508]）
    p_rest = cbc(b0[512:1024], KEY_CXD90045, iv)  # 明文块0 后 512B（第一块 CBC 用 tail 里的 IV）
    pblock0 = p_head + p_rest
    cs_stored, = struct.unpack('<H', pblock0[0:2]); cs_calc = frame_cs(pblock0)
    print(f'帧0 checksum: 存 {cs_stored:#06x} 算 {cs_calc:#06x} {"OK" if cs_stored == cs_calc else "不符!"}')
    payload = pblock0[4:]                      # 第一帧的 payload（508B 在 ECB 区）
    stored_crc, = struct.unpack('<I', payload[8:12])   # 头 CRC 存于 payload[8:12]，覆盖 payload[12:512]
    calc_crc = zlib.crc32(bytes(payload[12:512])) & 0xffffffff
    print(f'头 checksum: 存 {stored_crc:#010x} 算 crc32(payload[12:512])={calc_crc:#010x} {"OK" if stored_crc == calc_crc else "不符!"}')
    print(f'身份字段: modeType={payload[16]:c} luw={payload[20]:c} ver={payload[33]}.{payload[32]:02d} '
          f'model={struct.unpack("<I",payload[36:40])[0]:#x} region={struct.unpack("<I",payload[40:44])[0]}')

    if a.prove:
        # 往返：原样重加密，必须与密文逐字节相同
        re512 = ecb(p_head, KEY_AES, dec=False)
        re512b = cbc(p_rest, KEY_CXD90045, iv, dec=False)
        print(f'往返 512B(ECB): {"一致" if re512 == b0[:512] else "不一致"}；'
          f'往返 512B(CBC 首段): {"一致" if re512b == b0[512:1024] else "不一致"}')
        return 0

    if not a.out:
        print('需要 --out（或 --prove）'); return 2
    p = bytearray(payload[:512])
    changed = []
    if a.set_mode:
        p[16] = ord(a.set_mode); changed.append(f'modeType->{a.set_mode}')
    if a.set_region is not None:
        struct.pack_into('<I', p, 40, a.set_region); changed.append(f'region->{a.set_region}')
    if a.set_model is not None:
        struct.pack_into('<I', p, 36, a.set_model); changed.append(f'model->{a.set_model:#x}')
    if a.set_version:
        maj, _, mi = a.set_version.partition('.')
        p[33] = int(maj); p[32] = int(mi); changed.append(f'ver->{maj}.{mi}')
    if not changed:
        print('没有要改的字段'); return 2
    print('改动:', ', '.join(changed))
    struct.pack_into('<I', p, 8, zlib.crc32(bytes(p[12:512])) & 0xffffffff)
    newp_head = bytearray(p_head)
    newp_head[4:512] = p[0:508]                 # payload[0:508] -> p_head[4:512]
    struct.pack_into('<H', newp_head, 0, frame_cs(bytes(newp_head) + p_rest))  # 帧头 4B 也在密文区内
    newcs, = struct.unpack('<H', newp_head[0:2])
    print(f'帧0 checksum: {cs_stored:#06x} -> {newcs:#06x}')

    ct_head = ecb(bytes(newp_head), KEY_AES, dec=False)
    assert len(ct_head) == 512
    newb0 = ct_head + b0[512:1024]
    out = bytearray(data)
    out[off:off + 1024] = newb0
    # DEND CRC（覆盖 [0, len-12)）
    new_dend = zlib.crc32(bytes(out[:-12])) & 0xffffffff
    old_dend, = struct.unpack('>I', bytes(data[-4:]))
    struct.pack_into('>I', out, len(out) - 4, new_dend)
    print(f'DEND CRC: {old_dend:#010x} -> {new_dend:#010x}')
    open(a.out, 'wb').write(bytes(out))
    print(f'写出 {a.out}（{len(out)} B）。注意：尾部 256B 签名原样保留，'
          f'若验签覆盖到身份字段，相机会拒（这本身就是有用的实验结果）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
