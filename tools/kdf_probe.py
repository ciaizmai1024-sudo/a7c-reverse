#!/usr/bin/env python3
"""KDF 探针：QEMU 里 setkey(256) 的 key(7e68a34d…) 是不是从 0xF340F000 那 32 字节变换而来。
用法：python3 tools/kdf_probe.py [窗口 hex(默认 32 个零)] [目标 key hex]
"""
import hashlib, hmac, sys
try:
    from Crypto.Cipher import AES
    HAVE_AES = True
except Exception:
    HAVE_AES = False

DEFAULT_TARGET = '7e68a34d461f1388620c91d76ac1113f78efb47fa3d5b5be6d025a40cd14fc3b'
KEY90045 = bytes.fromhex('c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b')
PI = bytes.fromhex('27ae41e4649b934ca495991b7852b855')
SHA_EMPTY = bytes.fromhex('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')

win = bytes.fromhex(sys.argv[1]) if len(sys.argv) > 1 else b'\x00' * 32
T = bytes.fromhex(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TARGET)

ins = {'WIN': win, 'WIN+K': win + KEY90045, 'K+WIN': KEY90045 + win, 'K': KEY90045,
       'K16': KEY90045[:16], 'PI': PI, 'PI2': PI + PI, 'SHAempty': SHA_EMPTY,
       'SHAempty16': SHA_EMPTY[:16], 'e': b'', 'z1k': b'\x00' * 1024, 'z4k': b'\x00' * 4096}
hits = []


def rec(name, val):
    if not isinstance(val, (bytes, bytearray)):
        return
    if bytes(val[:32]) == T or T in bytes(val):
        hits.append(name)


for nm, d in ins.items():
    for h in ('md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512', 'sha3_256', 'blake2s'):
        try:
            v = hashlib.new(h, d).digest()
        except Exception:
            continue
        rec(f'{h}({nm})', v)
        rec(f'{h}^2({nm})', hashlib.new(h, v).digest())
        rec(f'{h}(hex({nm}))', hashlib.new(h, d.hex().encode()).digest())
    for hf, hs in ((hashlib.md5, 16), (hashlib.sha256, 32), (hashlib.sha1, 20)):
        for cnt in (1, 2, 1000, 4096, 10000):
            prev = b''
            for _ in range(cnt):
                prev = hf(prev + d).digest()
            rec(f'EVP_BytesToKey({hs},salt=NULL,cnt={cnt})[{nm}]', prev[:32])
    for kh in (hashlib.sha256, hashlib.md5, hashlib.sha1):
        for kn, kk in (('K', KEY90045), ('K16', KEY90045[:16]), ('PI', PI),
                       ('z32', b'\x00' * 32), ('e', b''), ('WIN', win)):
            try:
                rec(f'HMAC-{kh().name}[{kn}]({nm})', hmac.new(kk, d, kh).digest())
            except Exception:
                pass
    if HAVE_AES:
        for kn, kk in (('K', KEY90045), ('K16', KEY90045[:16]), ('PI', PI), ('PI2', PI + PI),
                       ('SHAempty16', SHA_EMPTY[:16]), ('SHAempty32', SHA_EMPTY),
                       ('WIN16', win[:16]), ('WIN32', win[:32] if len(win) >= 32 else None)):
            if not kk or len(kk) not in (16, 24, 32):
                continue
            pad = d if len(d) % 16 == 0 else d.ljust((len(d) // 16 + 1) * 16 or 16, b'\x00')
            try:
                c = AES.new(kk, AES.MODE_ECB)
                rec(f'AES-ECB-enc[{kn}]({nm})', c.encrypt(pad))
                rec(f'AES-ECB-dec[{kn}]({nm})', c.decrypt(pad))
            except Exception:
                pass
            try:
                c = AES.new(kk, AES.MODE_CBC, b'\x00' * 16)
                rec(f'AES-CBC-enc[{kn}]({nm})', c.encrypt(pad))
                c = AES.new(kk, AES.MODE_CBC, b'\x00' * 16)
                rec(f'AES-CBC-dec[{kn}]({nm})', c.decrypt(pad))
                c = AES.new(kk, AES.MODE_CTR, nonce=b'')
                rec(f'AES-CTR[{kn}]({nm})', c.encrypt(d))
            except Exception:
                pass

print('窗口输入 %d 字节: %s' % (len(win), win.hex()))
print('目标 key      :', T.hex())
print('AES 可用      :', HAVE_AES)
print('命中          :', '\n  '.join(hits) if hits else '无（这一层试探不中，需要在 libInfraSKD.so 里把 KDF 反汇编出来）')
