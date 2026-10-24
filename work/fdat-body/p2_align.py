#!/usr/bin/env python3
"""P2/P3: 明文流 = 512B UDTRFIRM 头 + object 表（obj1=updater cramfs, obj2=tar）。
本脚本:
 1) 按头部对象表切出两个 object（cramfs body / tar），列 tar 成员清单（名字/明文偏移/大小）
 2) 用真机分区 dump 的样本窗口在明文里 find，给出 明文偏移 ↔ 分区 对齐表
 3) 明文偏移 -> FDAT 帧/密文偏移 换算 + 64B 往返验证
 4) 压缩 magic 扫描（$Cram/$ Crom、lzma、deflate 采样）
 5) 额外搜 6157/664 的组合模式（4B 相邻对 + ASCII）于整个明文
用法: python3 work/fdat-body/p2_align.py [--quick]
"""
import mmap, os, struct, sys, zlib, subprocess

V = {'2.00': '/tmp/dec200.bin', '2.03': '/tmp/dec203.bin'}
DATDIR = {'2.00': '/tmp/ilce7c200/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV200.dat',
          '2.03': '/tmp/ilce7c203/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV203.dat'}
DUMPS = [
    ('nflasha1(l1)', 'work/l1-camera/nflasha1.bin'),
    ('nflasha1(l2)', 'work/l2-camera/nflasha1.bin'),
    ('nflasha2', 'work/l2-camera/nflasha2.bin'),
    ('nflasha3', 'work/l1_v/nflasha3.bin'),
    ('nflasha4', 'work/l2-camera/nflasha4.bin'),
    ('nflasha6', 'work/l2-camera/nflasha6.bin'),
    ('nflasha7', 'work/l1-camera/nflasha7.bin'),
    ('nflasha10', 'work/l2-camera/nflasha10.bin'),
    ('nflasha13', 'work/l2-camera/nflasha13.bin'),
    ('nflasha15', 'work/l2-camera/nflasha15.bin'),
    ('nflasha23', 'work/l2-camera/nflasha23.bin'),
    ('a1_203(tar)', 'work/v203/nflasha1_203.bin'),
    ('AV-CAM.BIN', 'work/a3-avcam/AV-CAM.BIN'),
]


def objtab(mm):
    h = mm[:0x200]
    o2off, o2len, nobj = struct.unpack_from('<III', h, 48)
    objs = []
    for i in range(4):
        b = 64 + i * 16
        mt, hlen, ln, x = struct.unpack_from('<4sIII', h, b)
        if mt[0:1] not in (b'\x00',):
            objs.append((i, mt, hlen, ln))
    return o2off, o2len, nobj, objs


def tar_members(mm, base, limit=400):
    """ustar/gnu: header 512B; name[100] mode[8] uid[8] gid[8] size[12oct] mtime[12oct] chksum[8] typeflag linkname[100] magic[6]='ustar' version[2]='00' uname[32] gname[32] ... prefix[155] @345(gnu/ustar)."""
    o = base
    end = base + 0x7fffffff
    out = []
    while len(out) < limit:
        hdr = mm[o:o + 512]
        if len(hdr) < 512 or hdr[:100] == b'\0' * 512 - b'\0' * 400 and hdr[:100].strip(b'\0') == b'':
            break
        if hdr[:100].strip(b'\0') == b'':
            break
        name = hdr[:100].split(b'\0')[0].decode('latin1')
        size = int(hdr[124:136].split(b'\0')[0] or b'0', 8)
        typ = hdr[156:157]
        magic = hdr[257:263]
        prefix = hdr[345:500].split(b'\0')[0].decode('latin1')
        if magic == b'ustar\0' and prefix:
            name = prefix + '/' + name
        # gnu longname: 'GNU'/'ustar  ' type 'L'
        out.append((o, name, size, typ.decode('latin1')))
        o += 512 + ((size + 511) // 512) * 512
        if typ == b'L':
            longname = mm[o - ((size + 511) // 512) * 512:o - ((size + 511) // 512) * 512 + size].split(b'\0')[0].decode('latin1')
            out[-1] = (out[-1][0], out[-1][1], out[-1][2], 'L')
            out.append((o, longname, None, 'pending'))
    return out


def tar_members2(mm, base, total):
    """Robust sequential tar walk; handles GNU longname (type 'L')."""
    o, end = base, base + total
    out = []
    pending_long = None
    while o + 512 <= end:
        hdr = bytes(mm[o:o + 512])
        if hdr[:512] == b'\0' * 512:
            break
        name = hdr[:100].split(b'\0')[0].decode('latin1')
        size = int(hdr[124:136].split(b'\0')[0] or b'0', 8)
        typ = hdr[156:157].decode('latin1')
        magic = hdr[257:263]
        prefix = hdr[345:500].split(b'\0')[0].decode('latin1')
        if magic in (b'ustar\0', b'ustar ') and prefix and not pending_long:
            name = prefix + '/' + name
        dataoff = o + 512
        if typ == 'L':
            pending_long = bytes(mm[dataoff:dataoff + size]).split(b'\0')[0].decode('latin1')
            o = dataoff + ((size + 511) // 512) * 512
            continue
        if pending_long:
            name = pending_long
            pending_long = None
        out.append((dataoff, name, size, typ))
        o = dataoff + ((size + 511) // 512) * 512
    return out


# ---- frame mapping ----
def build_frame_index(dat, nframes_max=400000):
    """decrypt frames -> cumulative plaintext lengths per frame. returns list of (plain_start, payload_len).
    Uses openssl decryption streaming per 1024B block batch to avoid huge memory? simpler: decrypt all."""
    B = open(dat, 'rb').read()
    dstart = 0xd4
    dend = B.rfind(b'\x00\x00\x00\x04DEND')
    data = B[dstart:dend - 8]
    body, tail = data[:-0x110], data[-0x110:]
    iv = tail[:16].hex()
    p = subprocess.run(['openssl', 'enc', '-d', '-aes-128-ecb', '-K',
                        'e3b0c44298fc1c149afbf4c8996fb924', '-nopad'], input=body[:512], capture_output=True)
    head512 = p.stdout
    n = 512 + ((len(body) - 512) // 16) * 16
    p = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-K',
                        'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b',
                        '-iv', iv, '-nopad'], input=body[512:n], capture_output=True)
    dec = head512 + p.stdout
    return data, dec


def frames_of(dec):
    idx = []  # (plain_start, cipher_off_within_FDATpayload, len)
    pi = 0
    i = 0
    n = len(dec) // 1024
    for k in range(n):
        fr = dec[k * 1024:k * 1024 + 4]
        se = struct.unpack_from('<H', fr, 2)[0]
        ln = se & 0xfff
        idx.append((pi, k * 1024, ln))
        pi += ln
        if (se >> 15) & 1:
            break
    return idx


def p2f(idx, pofs):
    """plaintext offset -> (frame k, off within frame payload 4..1024)."""
    lo, hi = 0, len(idx) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if idx[mid][0] <= pofs:
            lo = mid
        else:
            hi = mid - 1
    ps, coff, ln = idx[lo]
    return lo, pofs - ps, ps, coff


def main():
    quick = '--quick' in sys.argv
    for v, path in V.items():
        print(f'\n######## {v}: {path} ########')
        f = open(path, 'rb')
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        o2off, o2len, nobj, objs = objtab(mm)
        print(f'obj2(tar) off={o2off} len={o2len} nobj={nobj} objs={objs}')
        # objects sequential: obj at 512 (objtab said hlen=512 for entries @64,@80)
        # assume object data area starts right after 512-byte header? check cramfs magic
        print(f'  bytes@0x200: {mm[0x200:0x210].hex(" ")}  bytes@{o2off:#x}: {mm[o2off:o2off+16].hex(" ")}')
        obj0_len = objs[0][3]
        tar_base = 0x200 + 0x200 + obj0_len if o2off == 0x200 + 0x200 + obj0_len else o2off
        print(f'  obj0(cramfs) 明文范围 [0x200,{0x200+obj0_len:#x}) cramfs-magic={mm[0x200:0x204].hex(" ")} '
              f'cramfs-signature@0x210={mm[0x210:0x220]!r}')
        mem = tar_members2(mm, tar_base, mm.size() - tar_base)
        print(f'  tar members: {len(mem)} (base {tar_base})')
        with open(f'work/fdat-body/tarmembers_{v.replace(".","")}.tsv', 'w') as w:
            for d, nm, sz, ty in mem:
                w.write(f'{d}\t{sz}\t{ty}\t{nm}\n')
        for d, nm, sz, ty in mem:
            if 'dev/nflash' in nm or nm.endswith('.sum') or nm.endswith('.conf') or 'AV-CAM' in nm.upper():
                print(f'    @{d}(+0x{d:x}) size={sz} type={ty} {nm}')
        # alignment
        print('  -- 对齐真机 dump --')
        for label, dp in DUMPS:
            if not os.path.exists(dp):
                print(f'    {label}: 缺文件 {dp}')
                continue
            D = open(dp, 'rb').read()
            res = []
            for tag, off in (('head512', 0), ('+1KiB', 1024), ('+4KiB', 4096), ('+1MiB', 1 << 20),
                             ('+8MiB', 8 << 20), ('mid', (len(D) // 2) & ~0x3ff)):
                if off + 512 > len(D):
                    continue
                w = D[off:off + 512]
                if w.count(0) > 500:
                    continue
                i = mm.find(w)
                res.append((tag, off, i))
            hits = [r for r in res if r[2] >= 0]
            print(f'    {label} ({len(D)} B): ' + '; '.join(f'{t}@dump+{o:#x}->plain+{i:#x}' for t, o, i in res))
        # AV-CAM special: search whole
        # compression magic scan
        cnt = {}
        for mag in (b'$Cram', b'$Crom', b'7zXZ', b'\xfd7zXZ', b'$Bfr'):
            c, start = 0, 0
            first = None
            while True:
                i = mm.find(mag, start)
                if i < 0:
                    break
                c += 1
                if first is None:
                    first = i
                start = i + 1
                if c > 100000:
                    break
            cnt[mag] = (c, first)
        print('  -- 压缩 magic --', {k: v for k, v in cnt.items()})
        # 6157/664 combined patterns over full plaintext
        print('  -- 6157/664 组合模式（全明文） --')
        pats = {
            'LE16 6157|LE16 664': struct.pack('<HH', 6157, 664),
            'BE16 664|BE16 6157': struct.pack('>HH', 664, 6157),
            'LE16 6157|BE16 664': struct.pack('<H', 6157) + struct.pack('>H', 664),
            'LE32 6157': struct.pack('<I', 6157), 'BE32 6157': struct.pack('>I', 6157),
            'LE32 664': struct.pack('<I', 664), 'BE32 664': struct.pack('>I', 664),
            'ascii 6157:': b'6157:', 'ascii :664': b':664', 'ascii "6157"': b'"6157"', 'ascii "664"': b'"664"',
        }
        for nm, p in pats.items():
            hits, start = [], 0
            while len(hits) < 5:
                i = mm.find(p, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
            if hits:
                print(f'    {nm}: ' + ', '.join(hex(h) for h in hits))
        # frame mapping demo
        data, dec = build_frame_index(DATDIR[v])
        idx = frames_of(dec)
        print(f'  -- 帧索引: {len(idx)} 帧, 明文总长 {idx[-1][0]+idx[-1][2]} (文件 {mm.size()}) --')
        import bisect
        starts = [a for a, b, c in idx]
        for po in (0x0, 0x200, 0x1000, o2off, o2off + 100000, o2off + o2len - 100, mm.size() - 64):
            k = bisect.bisect_right(starts, po) - 1
            ps, coff, ln = idx[k]
            # verify: FDAT payload bytes at coff+4+(po-ps) == plaintext
            seg = data[coff + 4 + (po - ps):coff + 4 + (po - ps) + 16]
            # careful: plaintext is post-decryption; data here is CIPHERTEXT. verify via dec instead
            seg2 = dec[coff + 4 + (po - ps):coff + 4 + (po - ps) + 16]
            ok = seg2 == mm[po:po + 16]
            print(f'    plain@{po:#x} -> frame {k} (帧内偏移 {4+po-ps}, FDAT payload off {coff+4+po-ps}) '
                  f'ciphertext(dat文件) off {0xd4+coff+4+po-ps} 回读验证={ok}')
        mm.close()


if __name__ == '__main__':
    main()
