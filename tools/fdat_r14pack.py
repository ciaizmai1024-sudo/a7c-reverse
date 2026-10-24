#!/usr/bin/env python3
"""Round14: pack a plaintext UDTRFIRM stream into a card BODYDATA.DAT
(UFU container: DATV/PROV/UDID copied verbatim from an official .dat,
FDAT record re-framed/re-encrypted with public platform keys, DEND CRC recomputed).

  python3 tools/fdat_r14pack.py OFFICIAL.dat PLAIN.bin OUT [--sign KEY.pem] [--flip OFF]

  --sign: RSA-SHA256-sign msg = PLAIN[:-256]; last 256 B of the stream are replaced
          by the signature (pos: replaces the official stream's trailing zero region).
  --flip: xor one byte at OFF in the *stream* BEFORE packing (payload area) while the
          signature stays the one from the unflipped message (negative test).
Layout mirrors tools/fdat_aescbc.py (verified against official 2.00/2.03).
"""
import struct, sys, zlib, subprocess, hashlib

KEY_AES = 'e3b0c44298fc1c149afbf4c8996fb924'
KEY_90045 = 'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'
MAGIC = b'\x89UFU\r\n\x1a\n'


def openssl(data, *args):
    p = subprocess.run(['openssl', 'enc', *args, '-nopad'], input=data, capture_output=True)
    if p.returncode:
        raise SystemExit(p.stderr.decode())
    return p.stdout


def main():
    a = sys.argv[1:]
    opt = {k.lstrip('-'): v for k, v in zip(a[::2], a[1::2])} if False else None
    args = [x for x in a if not x.startswith('--sign') and not x.startswith('--flip')]
    # simple parse
    sign = None; flip = None
    i = 0
    while i < len(a):
        if a[i] == '--sign':
            sign = a[i + 1]; i += 2; continue
        if a[i] == '--flip':
            flip = int(a[i + 1], 0); i += 2; continue
        args.append(a[i]); i += 1
    official, plain_p, out_p = args[0], args[1], args[2]

    B = open(official, 'rb').read()
    assert B[:8] == MAGIC
    o = 8; recs = []
    while o + 8 <= len(B):
        n = struct.unpack('>I', B[o:o + 4])[0]; t = B[o + 4:o + 8]
        recs.append((t, B[o + 8:o + 8 + n])); o += 8 + n
        if t == b'DEND':
            break
    keep = [r for r in recs if r[0] in (b'DATV', b'PROV', b'UDID')]

    P = bytearray(open(plain_p, 'rb').read())
    sig = None
    if sign:
        msg = bytes(P[:-256])
        open('/tmp/r14msg.bin', 'wb').write(msg)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', sign,
                        '-out', '/tmp/r14sig.bin', '/tmp/r14msg.bin'], check=True)
        sig = open('/tmp/r14sig.bin', 'rb').read()
        assert len(sig) == 256
        P[-256:] = sig
    if flip is not None:
        P[flip] ^= 0x01
    print('stream', len(P), 'head', bytes(P[:8]))

    # frame
    F = bytearray()
    nchunk = (len(P) + 1019) // 1020
    for k in range(nchunk):
        pay = P[k * 1020:(k + 1) * 1020]
        fr = bytearray(1024)
        ln = len(pay) | (0x8000 if k == nchunk - 1 else 0)
        fr[2:4] = struct.pack('<H', ln)
        fr[4:4 + ln] = pay
        fr[4 + ln:] = b'\xff' * (1020 - len(pay))
        s = sum(struct.unpack('<511H', bytes(fr[2:1024]))) & 0xffff
        fr[0:2] = struct.pack('<H', s)
        F += fr
    # encrypt
    ecb = openssl(bytes(F[:512]), '-d' and '-aes-128-ecb', '-K', KEY_AES)  # encrypt
    iv = hashlib.md5(bytes(P[:64])).hexdigest()
    rest = openssl(bytes(F[512:]), '-aes-256-cbc', '-K', KEY_90045, '-iv', iv)
    data = ecb + rest
    # tail blob: encrypted copy of the (plaintext-domain) signature, CBC-continued
    lastblk = data[-16:]
    blob_src = (sig if sig else bytes(P[-256:]))
    blob = openssl(blob_src, '-aes-256-cbc', '-K', KEY_90045, '-iv', lastblk.hex())
    fdat = data + bytes.fromhex(iv) + blob

    cont = bytearray(MAGIC)
    for t, d in keep:
        cont += struct.pack('>I', len(d)) + t + d
    cont += struct.pack('>I', len(fdat)) + b'FDAT' + fdat
    crc = zlib.crc32(bytes(cont)) & 0xffffffff
    cont += struct.pack('>I', 4) + b'DEND' + struct.pack('>I', crc)
    open(out_p, 'wb').write(bytes(cont))
    print('wrote', out_p, len(cont), 'DEND crc %08x' % crc)


if __name__ == '__main__':
    main()
