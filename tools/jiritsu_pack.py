#!/usr/bin/env python3
"""构建 A7C(一代, CXD90045) Jiritsu 服务通道 FIRMUP(cmd 0x4006) 的 tar 载荷。

证据基础（逐指令，见 notes/jiritsu.md §4/§5 与 FIRMWARE_MOD.md §3.1.1）：
  adj_cmd_set_firm @0x67ec:
    0x6816  L > 0x500000            -> 状态 0x1000000f 'firm size over'      (载荷 <= 5 MiB)
    0x681a  '/tmp/jbusy' 必须不存在  -> 0x10000011 'jiritsu running'
    0x683a  sys_mount('/dev/nflasha6','/tmp/jiritsu',0)
    0x6870  mode&2 -> sys_tar_compress: '/bin/tar cf /tmp/jiritsu.bak.tar ./ -C /tmp/jiritsu' (+ MD5 -> .bak.hash)
    0x692e  ramdisk_mount('/tmp/jiritsu/ramdsk','size=5M'); 0x694a open('/tmp/jiritsu/ramdsk/jiritsu.dat',O_WRONLY|O_CREAT|O_TRUNC,0755)
    0x69d2  sys_tar_extract -> '/bin/tar xpf %s ./ -C %s'   (目标 = /tmp/jiritsu = nflasha6 挂载点)
    之后: 写 '/tmp/jiritsu/jiritsu.hash'(载荷 MD5)、删 '/tmp/jiritsu/jcount'、
          若 '/tmp/jiritsu/DIAC.csv' 存在 -> sens_list_update()（失败 0x10000009）
  相机 /bin/tar = busybox applet（nflasha7 rootfs 只有 busybox + 符号链接）=> 载荷用 ustar、条目必须以 './' 开头，
  并且**必须含一个 `./` 目录项**（否则相机自己的 busybox 1.29.3 解包后返回 rc=1）【实测：用相机自带的 busybox+glibc 2.11.2 在 arm32 容器里跑】。
  另：busybox tar 会把成员名里的 `../` 剔掉（“removing leading ‘../../’ from member names”）⇒ **tar 成员无法越出解包目录**【实测】。

libJit ABI（jit_thread @0x74b0 的 dlopen/dlsym 调用点）：
    CreateScriptI(void)                       -> 对象指针，0 = 失败          (0x76ec blx sb)
    LoadScriptI(obj, const char *scriptPath)  -> 非 0 = 成功, 0 = 失败       (0x77ba blx r6, 参数 r1='/tmp/jiritsu/tmmc.jit')
    RunScriptI(obj, void *paramStruct, char *name)                          (0x7a60 blx sl；调用前 open('/tmp/jbusy')，调用后 unlink)
    DestroyScriptI(obj)                                                       (release @0x7454: 参数 this+0x14)
"""
import argparse, os, subprocess, sys, tarfile, hashlib, io, struct

MAX_PAYLOAD = 0x500000          # 5 MiB 软件配额
REQUIRED_EXPORTS = ['CreateScriptI', 'LoadScriptI', 'RunScriptI', 'DestroyScriptI']
KEY_NAMES = ['libJit.so', 'tmmc.jit', 'DIAC.csv', 'ver.txt', 'jcount', 'jiritsu.hash', 'jit.log']


def elf_arm32_exports(path):
    """返回 (e_machine, 是否Thumb位可疑, 导出符号集合)。只解析 .dynsym/.dynstr。"""
    d = open(path, 'rb').read()
    if d[:4] != b'\x7fELF':
        return None
    ei_class, ei_data = d[4], d[5]
    if ei_class != 1 or ei_data != 1:
        return None
    e_machine, = struct.unpack('<H', d[18:20])
    shoff, = struct.unpack('<I', d[0x20:0x24])
    shentsize, = struct.unpack('<H', d[0x2e:0x30])
    shnum, = struct.unpack('<H', d[0x30:0x32])
    shstrndx, = struct.unpack('<H', d[0x32:0x34])
    so = struct.unpack('<I', d[shoff + shstrndx * shentsize + 16:shoff + shstrndx * shentsize + 20])[0]
    dynsym = dynstr = symtab = strtab = None
    for i in range(shnum):
        s = d[shoff + i * shentsize: shoff + (i + 1) * shentsize]
        nm = struct.unpack('<I', s[0:4])[0]
        ty, fl, addr, off, sz, link = struct.unpack('<6I', s[4:28])
        name = d[so + nm:].split(b'\0')[0].decode('latin1')
        if name == '.dynsym':
            dynsym = (off, sz, link)
        elif name == '.dynstr':
            dynstr = (off, sz)
        elif name == '.symtab':
            symtab = (off, sz, link)
    def resolve(link):
        o, s2 = None, None
        for i in range(shnum):
            s = d[shoff + i * shentsize: shoff + (i + 1) * shentsize]
            nm = struct.unpack('<I', s[0:4])[0]
            ty, fl, addr, off, sz, lk = struct.unpack('<6I', s[4:28])
            if i == link:
                return off, sz
        return None
    out = set()
    for tab in (dynsym, symtab):
        if not tab:
            continue
        off, sz, link = tab
        stro = resolve(link)
        if not stro:
            continue
        for i in range(sz // 16):
            st_name, st_value, st_size, info, other, shndx = struct.unpack('<IIIBBH', d[off + 16 * i: off + 16 * i + 16])
            if st_name:
                out.add(d[stro[0] + st_name:].split(b'\0')[0].decode('latin1'))
    return e_machine, out


def check_libjit(path, warn_only=False):
    r = elf_arm32_exports(path)
    problems = []
    if r is None:
        problems.append(f'{path}: 不是 32 位 LSB ELF')
    else:
        mach, syms = r
        if mach != 40:
            problems.append(f'{path}: e_machine={mach}（应为 40 = EM_ARM，一代是 32 位 ARM/Thumb）')
        missing = [s for s in REQUIRED_EXPORTS if s not in syms]
        if missing:
            problems.append(f'{path}: 缺少导出 {missing}')
    for p in problems:
        print('  ' + ('警告: ' if warn_only else '错误: ') + p)
    return not problems


def build(srcdir, outfile, dry=False):
    entries = []
    for root, dirs, files in os.walk(srcdir):
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = './' + os.path.relpath(full, srcdir)
            entries.append((rel, full))
    total = sum(os.path.getsize(f) for _, f in entries)
    print(f'载荷: {len(entries)} 个文件，明文合计 {total} B ({total/1048576:.2f} MiB)')
    if total > MAX_PAYLOAD:
        print(f'  错误: 超过 FIRMUP 配额 0x{MAX_PAYLOAD:x} (5 MiB)')
        return 2
    names = {n.split('/', 1)[1] for n, _ in entries if '/' in n}
    for k in KEY_NAMES:
        if k in names:
            print(f'  含已知名字: {k}')
    if 'libJit.so' not in names:
        print('  提示: 没有 libJit.so —— 若目标是代码执行，需要它（jit_thread 会复制并 dlopen）')
    if 'DIAC.csv' in names:
        print('  注意: 有 DIAC.csv -> set_firm 会调 sens_list_update()，失败即 0x10000009')
    if 'libJit.so' in names:
        if not check_libjit(os.path.join(srcdir, 'libJit.so')):
            return 3

    if dry:
        for n, f in entries:
            print(f'  {n}  ({os.path.getsize(f)} B)')
        return 0

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as t:
        # ★必须放一个 `./` 目录项作首个成员【实测：相机自己的 busybox 1.29.3 在容器里跑】
        # 相机解包命令是固定的 `/bin/tar xpf <载荷> ./ -C /tmp/jiritsu`（0x4676）。
        # 若归档里没有名为 `./` 的成员，busybox 会把文件**解出来但返回 rc=1**（“tar: .: not found in archive”）
        # → set_firm 可能把它当成解包失败（0x10000010）。相机自己 `tar cf F ./ -C DIR` 产出的归档首个成员就是 `./`，照它做。
        di = tarfile.TarInfo('./')
        di.type = tarfile.DIRTYPE
        di.mode = 0o755
        di.uid = di.gid = 0
        di.uname = di.gname = ''
        di.mtime = 0
        t.addfile(di)
        for rel, full in entries:
            ti = t.gettarinfo(full, arcname=rel)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ''
            t.addfile(ti, open(full, 'rb'))
    data = buf.getvalue()
    open(outfile, 'wb').write(data)
    print(f'写出 {outfile}: {len(data)} B，MD5={hashlib.md5(data).hexdigest()}')
    # 自检：busybox/系统 tar 能否列出（条目必须都是 './' 开头）
    p = subprocess.run(['tar', 'tf', outfile], capture_output=True, text=True)
    bad = [l for l in p.stdout.splitlines() if not l.startswith('./')]
    print(f'  tar tf 返回 {p.returncode}，非 ./ 开头的条目 {len(bad)} 个')
    if bad:
        print('  错误: 这些条目会被 busybox tar 拒绝或写到挂载点之外:', bad[:5])
        return 4
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('srcdir', nargs='?', default='.', help='要放进 Jiritsu 区(nflasha6) 的目录')
    ap.add_argument('-o', '--out', default='jiritsu.dat', help='输出 tar（就是发到相机的 jiritsu.dat 载荷）')
    ap.add_argument('--dry', action='store_true', help='只列清单不打包')
    ap.add_argument('--check-so', metavar='PATH', help='只检查一个 .so/.o：e_machine==40 且导出 4 个 Script 入口')
    a = ap.parse_args()
    if a.check_so:
        sys.exit(0 if check_libjit(a.check_so) else 3)
    sys.exit(build(a.srcdir, a.out, a.dry))
