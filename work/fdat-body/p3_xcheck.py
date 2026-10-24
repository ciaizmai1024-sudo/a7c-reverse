#!/usr/bin/env python3
"""P2b/P3: 帧映射换算 + 分区/成员精确对齐 + .sum CRC 交叉验证 + 6157/664 结构搜索 + AV-CAM 两版偏移差。

修正: p2_align.py 里 build_frame_index 的 DEND 定位差 8 字节导致 IV 错位；本脚本已修正。
"""
import mmap, os, struct, subprocess, sys, zlib

KEY_AES = 'e3b0c44298fc1c149afbf4c8996fb924'
KEY9 = 'c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b'
V = {'2.00': ('/tmp/dec200.bin', '/tmp/ilce7c200/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV200.dat'),
     '2.03': ('/tmp/dec203.bin', '/tmp/ilce7c203/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV203.dat')}
MEM = {'2.00': 'work/fdat-body/tarmembers_200.tsv', '2.03': 'work/fdat-body/tarmembers_203.tsv'}


def load_frames(dat):
    B = open(dat, 'rb').read()
    dend = B.rfind(b'\x00\x00\x00\x04DEND')          # DEND 记录 len 字段偏移 = FDAT payload 结束
    dstart = 0xdc                                    # FDAT 记录 data 起点 (rec@0xd4: len+type+data)
    data = B[dstart:dend]                            # FDAT payload（含 272B 尾）
    assert struct.unpack_from('>I', B, dstart - 8)[0] == len(data), (struct.unpack_from('>I', B, dstart - 8)[0], len(data))
    body, tail = data[:-0x110], data[-0x110:]
    iv = tail[:16].hex()
    h = subprocess.run(['openssl', 'enc', '-d', '-aes-128-ecb', '-K', KEY_AES, '-nopad'],
                       input=body[:512], capture_output=True).stdout
    n = 512 + ((len(body) - 512) // 16) * 16
    r = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-K', KEY9, '-iv', iv, '-nopad'],
                       input=body[512:n], capture_output=True).stdout
    dec = h + r
    idx = []          # (plain_start, frame_cipher_off_in_FDATpayload)
    pi = 0
    k = 0
    while True:
        se = struct.unpack_from('<H', dec, k * 1024 + 2)[0]
        ln = se & 0xfff
        idx.append((pi, k * 1024, ln))
        pi += ln
        if (se >> 15) & 1:
            break
        k += 1
        _ = 0
    return data, dec, idx, pi


def bisect(idx, p):
    lo, hi = 0, len(idx) - 1
    while lo < hi:
        m = (lo + hi + 1) // 2
        if idx[m][0] <= p:
            lo = m
        else:
            hi = m - 1
    return lo


def show_map(idx, plain_mm, dat_off, points):
    for p in points:
        k = bisect(idx, p)
        ps, co = idx[k]
        f = 4 + (p - ps)
        fdat = co + f
        seg = None
        c = None
        if p + 16 <= plain_mm.size():
            c = plain_mm[p:p + 16]
        seg = None
        # 回读验证需要 dec（解密后帧流）——调用方传入
        print(f'    plain@{p:#x} -> 帧 k={k} 帧内={f} FDATpayload@{fdat:#x} .dat@{dat_off+fdat:#x}')


def main():
    for v, (dec_path, dat) in V.items():
        print(f'\n######## {v} ########')
        data, dec, idx, ptot = load_frames(dat)
        f = open(dec_path, 'rb')
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        print(f'帧数={len(idx)} 末帧明文起点={idx[-1][0]} 明文总长={ptot} (文件 {mm.size()}) '
              f'FDAT payload={len(data)} B, 帧区={len(idx)*1024}, 尾={len(data)-len(idx)*1024}')
        # 64B 往返验证（若干点）
        for p in (0, 0x1ff, 0x200, 0x400, 0x1234, 100000, mm.size() - 64):
            k = bisect(idx, p)
            ps, co, ln = idx[k]
            fpos = co + 4 + (p - ps)
            span = min(64, ln - (p - ps))
            ok = dec[fpos:fpos + span] == mm[p:p + span]
            print(f'  往返 plain[{p:#x},+64) -> 帧{k} 帧内{4+p-ps} FDATpayload {fpos:#x} '
                  f'-> .dat {0xdc+fpos:#x} : {"✓" if ok else "✗"}')
        # 帧换算式演示: 也演示反向
        # members
        mem = []
        for line in open(MEM[v]):
            d, sz, ty, nm = line.rstrip('\n').split('\t')
            mem.append((int(d), int(sz), ty, nm))
        dev = [(d, s, nm) for d, s, t, nm in mem if '/dev/nflash' in nm]
        # .sum 交叉验证
        for d, s, t, nm in mem:
            if nm.endswith('.sum'):
                txt = mm[d:d + s].decode('latin1')
                print(f'  --- {nm} ({s} B) ---')
                for ln in txt.strip().split('\n'):
                    print('   ', ln)
                    fld = ln.split(',')
                    if len(fld) >= 3 and fld[1] != 'ffffffff':
                        want = int(fld[1], 16)
                        size = int(fld[2], 16)
                        path = fld[-2] if fld[-1] == '' else fld[-1]
                        # 找该段里对应成员（相对路径在 sum 所在段内）
                        sec = nm.split('/')[0][:4]
                        cand = [(dd, ss, nn) for dd, ss, t2, nn in mem
                                if nn.startswith(nm.split('/')[0][:-4] + '_') or True]
                        # 直接: 找名字尾段匹配的成员
                        tgt = [x for x in mem if x[3].endswith(path) and x[1] == size and x[2] == '0']
                        if tgt:
                            dd, ss, t2, nn = tgt[0]
                            c = 0
                            q = dd
                            while q < dd + ss:
                                blk = mm[q:min(q + 65536, dd + ss)]
                                c = zlib.crc32(blk, c)
                                q += 65536
                            print(f'      成员 {nn} @{dd:#x} 实测 crc32={c & 0xffffffff:08x} '
                                  f'{"✓" if (c & 0xffffffff) == want else "✗"} (sum 存 {fld[1]}) size={ss}')
        # 精确对齐: dev 成员 vs 真机 dump
        DUMPS = {'nflasha1': 'work/l1-camera/nflasha1.bin', 'nflasha3': 'work/l1_v/nflasha3.bin',
                 'nflasha7': 'work/l1-camera/nflasha7.bin', 'nflasha15': 'work/l2-camera/nflasha15.bin',
                 'nflasha1_203': 'work/v203/nflasha1_203.bin'}
        for d, s, nm in dev:
            key = nm.split('/')[-1]
            dp = DUMPS.get(key) if key in DUMPS else None
            if dp is None and key == 'nflasha1':
                dp = DUMPS.get('nflasha1_203')
            if not dp or not os.path.exists(dp):
                continue
            D = open(dp, 'rb')
            # 流式比较成员 vs dump 前缀
            same = 0
            D.seek(0)
            firstbad = None
            while same < min(s, os.path.getsize(dp)):
                n = min(1 << 20, min(s, os.path.getsize(dp)) - same)
                a = mm[d + same:d + same + n]
                b = D.read(n)
                if a != b:
                    for i in range(len(a)):
                        if a[i] != b[i]:
                            firstbad = same + i
                            break
                    break
                same += n
            print(f'  对齐 {nm} @{d:#x} len={s} vs {dp}: 前缀相同 {same} B, 首个差异 @{firstbad if firstbad is None else hex(firstbad)}')
        # 压缩痕迹（只在 tar 成员范围内找 $Cram/$Crom）
        cnt = mm.find(b'$Cromfs'), mm.find(b'$Cramfs')
        print(f'  $Cromfs@{cnt[0]} $Cramfs@{cnt[1]}  (cramfs 外显 magic: 明文里 0x200 处 = {mm[0x200:0x204].hex()} '
              f'{mm[0x210:0x220]!r}; a1 initrd cramfs magic 45 3d cd 28 出现次数=', end='')
        c, st = 0, 0
        firsts = []
        while True:
            i = mm.find(b'\x45\x3d\xcd\x28', st)
            if i < 0 or c > 40:
                break
            c += 1
            if len(firsts) < 8:
                firsts.append(i)
            st = i + 1
        print(f'{c}+  位置样例 {[hex(x) for x in firsts]}')
        # AV-CAM: 找 FAT 目录项 'AV-CAM  BIN'
        st = 0
        while True:
            i = mm.find(b'AV-CAM  BIN', st)
            if i < 0:
                break
            print(f'  目录项 AV-CAM.BIN @plain {i:#x}: entry={mm[i-11:i+32-11].hex(" ")}')
            st = i + 1
        # 2.00 AV-CAM 数据头 512B 在两版中的位置（测偏移差）
        st = 0
        while True:
            i = mm.find(b'AV-CAM.BIN', st)
            if i < 0 or i > 0x16000000:
                break
            print(f'  字符串 "AV-CAM.BIN" @plain {i:#x} ctx={mm[i-32:i+32].hex(" ")}')
            st = i + 1
        mm.close()


if __name__ == '__main__':
    main()
