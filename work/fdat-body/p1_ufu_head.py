#!/usr/bin/env python3
"""P1: UFU 容器记录 + UDTRFIRM 头字段两版对照 + 6157/664 搜索。

产物: stdout 报告（同时 tee 到 work/fdat-body/p1_report.txt）
"""
import struct, sys, zlib, re

DATS = {
    '2.00': '/tmp/ilce7c200/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV200.dat',
    '2.03': '/tmp/ilce7c203/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV203.dat',
}
DEC = {'2.00': '/tmp/dec200.bin', '2.03': '/tmp/dec203.bin'}


def ufu_records(path):
    B = open(path, 'rb').read()
    out, o = [], 8
    while o + 8 <= len(B):
        n = struct.unpack_from('>I', B, o)[0]
        t = B[o + 4:o + 8]
        out.append((o, t, n, B[o + 8:o + 8 + n]))
        o += 8 + n
    return B, out


def hexs(b, n=96):
    return ' '.join(f'{c:02x}' for c in b[:n])


def parse_head(h):
    f = {}
    f['magic'] = h[:8]
    f['hdr_crc32@8(BE?)'] = struct.unpack_from('>I', h, 8)[0]
    f['stored_le'] = struct.unpack_from('<I', h, 8)[0]
    f['fmt@12'] = h[12:16]
    f['modeType@16'] = h[16:20]
    f['u32@20'] = struct.unpack_from('<I', h, 20)[0]
    f['bytes@24..31'] = hexs(h[24:32], 8)
    f['ver@32'] = hexs(h[32:36], 4)
    f['model@36'] = hex(struct.unpack_from('<I', h, 36)[0])
    f['region@40'] = struct.unpack_from('<I', h, 40)[0]
    f['u32@44'] = struct.unpack_from('<I', h, 44)[0]
    f['obj2_off@48'] = struct.unpack_from('<I', h, 48)[0]
    f['obj2_len@52'] = struct.unpack_from('<I', h, 52)[0]
    f['nobj@56'] = struct.unpack_from('<I', h, 56)[0]
    for i in range(4):
        b = 64 + i * 16
        f[f'obj{i}@{b}'] = (h[b:b + 4], struct.unpack_from('<I', h, b + 4)[0],
                            struct.unpack_from('<I', h, b + 8)[0],
                            struct.unpack_from('<I', h, b + 12)[0])
    f['hdr_crc32_calc crc32(h[12:512])'] = hex(zlib.crc32(h[12:512]) & 0xffffffff)
    return f


def search_pattern(plain, pat, limit=20):
    hits, start = [], 0
    while len(hits) < limit:
        i = plain.find(pat, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    return hits


def main():
    vers = ['2.00', '2.03']
    for v in vers:
        B, recs = ufu_records(DATS[v])
        print(f'== UFU 记录 {v} ({len(B)} B) ==')
        for off, t, n, data in recs:
            print(f'  rec@{off:#x} type={t.decode("latin1")} len={n}')
        dend_off, _, _, dend_data = recs[-1]
        print(f'  DEND stored={struct.unpack(">I", dend_data)[0]:#010x} calc crc32(B[:dend_off+12-4])={zlib.crc32(B[:dend_off+12-4])&0xffffffff:#010x}')
        for off, t, n, data in recs:
            if t in (b'DATV', b'PROV'):
                print(f'  {t.decode()} payload: {hexs(data, 64)}')
            elif t == b'UDID':
                cnt = struct.unpack_from('>I', data, 0)[0]
                print(f'  UDID len={n} be32count={cnt} payload hex ({min(n,1024)} B):')
                for i in range(0, min(n, 1024), 32):
                    print(f'    {i:#04x}  {hexs(data[i:i+32], 32)}')
                print(f'  UDID tail: {hexs(data[-32:], 32)}')
            elif t == b'FDAT':
                print(f'  FDAT: head 0x40 {hexs(data, 64)}')
                print(f'  FDAT tail 0x110 first 0x20: {hexs(data[-0x110:], 32)}')
                print(f'  FDAT last 256 B (signature?): {hexs(data[-256:], 48)}...')
                # verify signature-region crc etc
                sig = data[-256:]
                msg = data[:n - 0x100]
                print(f'  FDAT msg[0:24] sha? (skip) sig[0:8]={hexs(sig,8)}')
            elif t == b'DEND':
                pass
        print()
    # header fields side by side
    hs = {}
    for v in vers:
        with open(DEC[v], 'rb') as f:
            hs[v] = f.read(0x2000)
    print('== UDTRFIRM 头字段对照 (0..0x200) ==')
    fa, fb = parse_head(hs['2.00'][:0x200]), parse_head(hs['2.03'][:0x200])
    for k in fa:
        mark = '' if fa[k] == fb[k] else '   <<< DIFF'
        print(f'  {k}: 2.00={fa[k]}  | 2.03={fb[k]}{mark}')
    print('\n== 0x1C0..0x210 raw ==')
    for v in vers:
        print(f'  {v}:')
        for i in range(0x1c0, 0x210, 32):
            print(f'    {i:#05x}  {hexs(hs[v][i:i+32], 32)}')

    # 6157 / 664 search
    print('\n== 6157(0x180D)/664(0x0298) 搜索 ==')
    pats = {
        'LE16 6157': struct.pack('<H', 6157), 'BE16 6157': struct.pack('>H', 6157),
        'LE16 664': struct.pack('<H', 664), 'BE16 664': struct.pack('>H', 664),
        'LE32 6157': struct.pack('<I', 6157), 'BE32 6157': struct.pack('>I', 6157),
        'LE32 664': struct.pack('<I', 664), 'BE32 664': struct.pack('>I', 664),
        'ascii 6157': b'6157', 'ascii 664': b'664', 'ascii "6157:664"': b'6157:664',
    }
    for v in vers:
        B, recs = ufu_records(DATS[v])
        for off, t, n, data in recs:
            for name, p in pats.items():
                hits = search_pattern(data, p, 6)
                if hits and not (t == b'FDAT' and len(hits) > 100):
                    for h in hits[:4]:
                        print(f'  {v} {t.decode()} rec@{off:#x} +{h:#x} ({h}): {name} ctx={hexs(data[max(0,h-12):h+20], 32)}')
        with open(DEC[v], 'rb') as f:
            head = f.read(0x2000)
        for name, p in pats.items():
            for h in search_pattern(head, p, 6):
                print(f'  {v} PLAIN-head +{h:#x}: {name} ctx={hexs(head[max(0,h-12):h+20], 32)}')
        # whole plaintext counts (only for 16-bit forms, to gauge noise)
        with open(DEC[v], 'rb') as f:
            pass


if __name__ == '__main__':
    main()
