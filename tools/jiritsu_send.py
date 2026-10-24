#!/usr/bin/env python3
"""jiritsu_send.py — A7C(一代, ILCE-7C v2.00, CXD90045) 服务模式 Senser/Jiritsu 发送工具。

底层复用 ma1co/Sony-PMCA-RE 的 Senser 鉴权与分包（refs/Sony-PMCA-RE），
Jiritsu 层（block=0x1001 + code）按本项目逐指令结论实现（notes/jiritsu.md、notes/camtool.md）：

  PFUNC 0x40  AdjustControl : {u16 block=0x1001; u16 code} + 载荷
    code 2  MOUNT        挂 /dev/nflasha6 -> /tmp/jiritsu
    code 3  FORMAT       ⚠同芯片实测会卡死服务，默认拒发
    code 4  START        起 Jiritsu 引擎（会把 libJit.so dlopen）
    code 5  DEBUG        一代是空桩，但有副作用：把时钟设成 2017-07-04 21:42:26 ⇒ 默认拒发
    code 6  FIRMUP       刷 tar 载荷 ⚠同芯片实测会卡死服务，默认拒发
    code 15 SET_FILE_PATH 小头 1 字节 mode（=0 才对）+ 路径 + NUL
    code 16 SET_FILE2     小头 mode,id,flag（camtool 实测用 0x00,0xff,0x00）+ 内容  ← 写 libJit.so 的唯一通道
    code 17 GET_FILE2     小头 mode,id,flag（0x00,0xff,0x00）
    code 18 DELETE2       小头 mode,id；末尾 '/' ⇒ 递归删；否则 glob()+unlink ⇒ 通配符会展开 ⚠
  PFUNC 0xff01 FileControl : {u16 cmd(1=写,2=读,3=删); u16 nameSize} + 文件名(4 对齐) [+ 数据]；**可整段读块设备**
  PFUNC 0xff03 MemoryDump  : {u32 base; u32 size}

约定：Jiritsu 的 response 字节 0 = 成功、非 0 = 出错；FileControl/ProductInfo 的 response 字节 1 = 成功。

执行边界（2026-10-23 起，落在代码里）：
  * 默认 RO：写类子命令 fput/put/del/fdel 没有 --allow-write 一律拒绝（退出码非 0）。
  * --allow-write 还要 --level <名字>（默认 L2.5），目标路径必须在 WRITE_WHITELIST（写死在本文件里）该级名单内；
    L2.5 只允许 zzprobe 探针；/usr/lib/zzprobe 是「边界探针」——只允许失败，真写进去反而 exit 4 停序列。
  * 危险 opcode 0x4003 FORMAT / 0x4004 START / 0x4005 DEBUG / 0x4006 FIRMUP：硬挡，必须 --i-know-what-im-doing，且发前打印警告。
  * 写不自动重试：SET_FILE2(16)/DELETE2(18)/FORMAT/FIRMUP/raw 一律只发一次（pkt retries=0）；
    FileControl 写(0xff01 cmd=1) 不经 pkt 重试环，本就单发。
  * preflight 子命令：六项开工自检（设备身份/FW 版本/工具 sha/备份清单/mode 旗标/RO-RW 声明），支持 --mock。

USB：本机实测 A7C（2.00，机身 USB 当前模式）= **054C:0D29**（产品串 `ILCE-7C`）。
包内 UDID 白名单（`tools/ufu_scan.py` 解出，2.00/2.03 同）里 A7C 认的正常 PID =
`0448 047d 05fe 05ff 0501 0502 05a7 05a8 05ee 05ef 05c9 05ca 0513 0514 050d 050e 0511 0512 0528 0529`，
flag=2（更新器模式）= `054c:03e2`。pmca 侧：Senser 服务模式 = `0x02a9/0x0336`，更新器 = `0x033a/0x03e2`。
认证后服务模式仍按 `--svc-pid`（默认 0x0336,0x02A9）找。

依赖：pyusb + libusb（本机 venv：.venv-jir）。`frames` 子命令不需要相机也不需要 pyusb。
"""
import argparse
import hashlib
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PMCA = os.path.join(ROOT, 'refs', 'Sony-PMCA-RE')
# Sony-PMCA-RE 目录名带连字符，不能直接当包名 import；建一个 pmca 软链接再 import
PMCA_PARENT = os.path.join(ROOT, 'refs', '_pmca_pkg')
if PMCA_PARENT not in sys.path:
    try:
        os.makedirs(PMCA_PARENT, exist_ok=True)
        _link = os.path.join(PMCA_PARENT, 'pmca')
        if not os.path.lexists(_link):
            os.symlink(PMCA, _link)
        sys.path.insert(0, PMCA_PARENT)
    except OSError:
        PMCA_PARENT = None
if PMCA_PARENT is None and PMCA not in sys.path:
    sys.path.insert(0, PMCA)

VENDOR = 0x054C
MSC_PIDS = [0x0D29, 0x0D28, 0x0D2A, 0x0E8A, 0x0D95, 0x0D96, 0x0994]   # A7C 实测优先（0D29），其余为其他机型/模式
SVC_PIDS = [0x0336, 0x02A9]
NORM_PIDS = [0x0448, 0x047D, 0x05FE, 0x05FF, 0x0501, 0x0502, 0x05A7, 0x05A8, 0x05EE, 0x05EF,
             0x05C9, 0x05CA, 0x0513, 0x0514, 0x050D, 0x050E, 0x0511, 0x0512, 0x0D28, 0x0D29,
             0x0BFE, 0x0BFF, 0x0C01, 0x0C02, 0x0CA7, 0x0CA8, 0x0BEE, 0x0BEF, 0x0CC9, 0x0CCA,
             0x0C13, 0x0C14, 0x0D0D, 0x0D0E, 0x0D11, 0x0D12, 0x0D94, 0x0D95]
UPD_PIDS = [0x03E2, 0x033A]

MODE_HINT = {
    0x0D29: 'A7C 实测当前模式（产品串 ILCE-7C）', 0x0D2A: 'A7C MTP/PTP 模式（06/01/01，macOS 不绑驱动，claim 实测 OK）', 0x0D28: 'A7C 正常模式变体', 0x0D94: 'ZV-E10 正常模式', 0x0D95: 'ZV-E10 正常模式', 0x0D96: 'ZV-E10 变体',
    0x0E8A: 'MSC（旧假设）', 0x0994: 'HID/电脑遥控',
    0x0336: '服务模式 Senser（目标）', 0x02A9: '服务模式 Senser（旧机型）',
    0x033A: '更新器模式', 0x03E2: '更新器模式（包内 UDID 表 flag=2）',
}
CODES = {
    1: 'MODE', 2: 'MOUNT', 3: 'FORMAT', 4: 'START', 5: 'DEBUG', 6: 'FIRMUP', 7: 'SET_FILE',
    8: 'GET_FILE', 9: 'FILE_DELETE', 10: 'GET_FILELIST', 11: 'GET_FILE_HASH', 12: 'COMPARE_MEDIA',
    13: 'GET_VERSION', 14: 'FACTORY', 15: 'SET_FILE_PATH', 16: 'SET_FILE2', 17: 'GET_FILE2', 18: 'DELETE2',
}
DANGER = {3: 'FORMAT：会格式化 Jiritsu 分区（同芯片实测还会卡死服务）',
          6: 'FIRMUP：刷 Jiritsu 分区（同芯片实测会卡死服务）',
          5: 'DEBUG：一代是空桩，但会把时钟设成 2017-07-04 21:42:26',
          18: 'DELETE2：末尾带 / 会递归删；含 * ? [] 会 glob 展开'}
# 危险 opcode（Jiritsu code）：默认硬挡，要发必须 --i-know-what-im-doing
DANGER_OPCODES = (3, 4, 5, 6)          # 0x4003 FORMAT / 0x4004 START / 0x4005 DEBUG / 0x4006 FIRMUP
# 写类路径白名单（执行边界；改这里 = 改边界，改完必须重跑 preflight + mock_faults）
WRITE_WHITELIST = {
    # ★路径长度全部**避开 4 的倍数**：两种补白语义只在 len%4==0 时分叉（见 _fc 注释）。
    #   原名全部踩坑：/tmp/zzprobe=12、/setting/updater/zzprobe=24、/tmp/jiritsu/zzprobe=20、/usr/lib/zzprobe=16。
    'L2.5': {
        '/tmp/zzprobe1':             '边界探针：/tmp(nflasha10) 写探针（13 B，len%4=1）',
        '/setting/updater/zzprobe1': '边界探针：/setting/updater 写探针（25 B，len%4=1）',
        '/tmp/jiritsu/zzprobe1':     '边界探针：Jiritsu 区写探针（21 B；落 a10 还是 a6 要先定挂载态）',
        '/usr/lib/zzprobe1':         'BOUNDARY-PROBE 只允许失败（17 B）：真写成功 => 非预期，exit 4 停序列待人工确认',
    },
    'L4-jit': {
        '/tmp/jiritsu/libJit.so':   '部署 JIT worker（SET_FILE2，会触发 dlopen）',
    },
}
TOOL_HASH_FILE = os.path.join(ROOT, 'work', 'TOOL_HASH')
MANIFEST_FILE = os.path.join(ROOT, 'work', 'BACKUP_MANIFEST.tsv')
EXP_DEV = (0x054C, 0x0D29, 0x0200, 'ILCE-7C')   # MSC 实机：PID 0d29 + bcdDevice 0x200 + product ILCE-7C（0d2a=MTP，Senser 不通）


def gate_write(args, path, op):
    """写类子命令的执行边界。默认 RO；写 = --allow-write + 路径在 --level 白名单里。返回白名单备注。"""
    if not getattr(args, 'allow_write', False):
        raise SystemExit(f'拒绝 {op} {path}：工具默认 RO（只读），写被门禁拦下。\n'
                         f'  哪一级：加 --allow-write 与 --level <名字>（现有级别：{", ".join(WRITE_WHITELIST)}）\n'
                         f'  白名单在哪：tools/jiritsu_send.py 里写死的 WRITE_WHITELIST 表（路径必须在所选级别内）')
    lvl = getattr(args, 'level', None) or 'L2.5'
    wl = WRITE_WHITELIST.get(lvl)
    if wl is None:
        raise SystemExit(f'拒绝 {op}：--level {lvl} 不在级别表里（现有：{", ".join(WRITE_WHITELIST)}）')
    if path not in wl:
        raise SystemExit(f'拒绝 {op} {path}：路径不在 --level {lvl} 白名单内。\n'
                         f'  该级允许：{", ".join(sorted(wl))}\n'
                         f'  要加路径就改 tools/jiritsu_send.py 的 WRITE_WHITELIST，改完重跑 preflight 与 mock_faults')
    return wl[path]


STATUS = {0x10000005: 'ramdisk 挂载失败', 0x10000009: '空间/配额或写失败（/tmp=nflasha10 只有 12MB）',
          0x10000010: 'tar 解包失败', 0x10000011: 'jiritsu running（/tmp/jbusy 存在）',
          0x10000000: '空文件/非法 ELF（dlopen 干净失败）', 130: 'nflasha6 未挂载（读 /tmp/jiritsu 会返回它）'}


def hx(b, n=48):
    return (b[:n].hex() + ('…' if len(b) > n else '')) if b else ''


class Jiritsu:
    """Senser 通道上的 Jiritsu/FileControl 封装。"""

    def __init__(self, auth, dev, cam, verbose=False, pad='pmca'):
        self.auth, self.dev, self.cam, self.verbose, self.pad = auth, dev, cam, verbose, pad

    # ---- 底层 ----
    def pkt(self, pfunc, data, retries=2, delay=0.6, outFile=None):
        last = None
        for i in range(retries + 1):
            try:
                if self.verbose:
                    print(f'  -> PFUNC 0x{pfunc:04x} len={len(data)} {hx(data, 32)}')
                return self.dev.sendSenserPacket(pfunc, data, outFile)
            except Exception as e:                      # 相机偶尔 >5s 才回，退避重试
                last = e
                if i < retries:
                    time.sleep(delay * (i + 1))
        raise last

    def jir(self, code, payload=b'', retries=2, allow_danger=False):
        name = CODES.get(code, f'0x{code:04x}')
        if code in DANGER and not allow_danger:
            raise SystemExit(f'拒绝发送 code {code} {name}：{DANGER[code]}（硬挡；要发必须 --i-know-what-im-doing）')
        if code in DANGER:
            print(f'  ⚠⚠ 危险 opcode 放行：code {code} {name} —— {DANGER[code]}')
        # ★写/不可逆 opcode 单发：SET_FILE2(16)、DELETE2(18)、4/5/6 —— 绝不因超时就重发（重发=同一文件可能被写多次）
        resp, out = self.pkt(0x40, struct.pack('<HH', 0x1001, code) + payload,
                             retries=0 if code in (3, 4, 5, 6, 16, 18) else retries)
        st = struct.unpack_from('<I', out)[0] if len(out) >= 4 else None
        if resp or (st not in (None, 0)):
            print(f'  ! {name}: response={resp} status={st if st is None else hex(st)}'
                  f'{" (" + STATUS[st] + ")" if st in STATUS else ""} data={hx(out[4:], 32)}')
        return resp, st, (out[4:] if len(out) > 4 else b'')

    # ---- Jiritsu 文件通道 ----
    def sel(self, path, mode=0):
        return self.jir(15, bytes([mode]) + path.encode('latin1') + b'\0')

    def read2(self, path, mode=0, sid=0xff, flag=0):
        self.sel(path)
        return self.jir(17, bytes([mode, sid, flag]))

    def write2(self, path, data, mode=0, sid=0xff, flag=0):
        self.sel(path)
        return self.jir(16, bytes([mode, sid, flag]) + data)

    def delete2(self, path, mode=0, sid=0xff, allow_danger=True):
        self.sel(path)
        return self.jir(18, bytes([mode, sid]), allow_danger=allow_danger)

    # ---- FileControl（任意路径 / 块设备）----
    # ★补白语义有分歧，未判明：pmca(sony.py:999) 与同芯片实证的 camtool(jiritsu_lib.py:155/161/167)
    # 都用 `4 - len%4`（名字已 4 对齐时还多补 4 个 NUL）；我们早前改成 `(-len)%4`（已对齐不补）。
    # 两者**只在 len%4==0 时分叉**；而真机的 FileControl 一直就是 pmca 那份实现（没改过），
    # 所以上一轮“改 padding 才能读”的结论并不成立 ⇒ 用 padtest 一次 A/B 判定。
    # 本轮做法：默认沿用 pmca/camtool 语义（--pad pmca），并把探针路径长度全部避开 4 的倍数。
    def _fc(self, cmd, path, data=b'', outFile=None):
        fn = path.encode('latin1')
        padn = (4 - len(fn) % 4) if self.pad == 'pmca' else ((-len(fn)) % 4)
        fn += b'\0' * padn
        hdr = struct.pack('<HH', cmd, len(fn))
        res, out = self.dev.sendSenserPacket(0xff01, hdr + fn + data, outFile)
        if res != 1:
            raise Exception(f'FileControl 错误 response={res} path={path} len={len(path)} 补白={padn} nameSize={len(fn)}')
        return out

    def fread(self, path, outFile=None):
        return self._fc(2, path, b'', outFile)

    def fwrite(self, path, data):
        return self._fc(1, path, data)

    def fdel(self, path):
        return self._fc(3, path)

    def stop(self):
        try:
            self.auth.stop()
        except Exception:
            pass


def backend():
    import usb.backend.libusb1
    try:
        import libusb_package
        p = None
        try:                                        # libusb-package 1.0.30 在 macOS 上 find_library() 返回 None（已知怪癖）
            p = libusb_package.get_library_path()
        except Exception:
            p = None
        if p:
            return usb.backend.libusb1.get_backend(find_library=lambda n: str(p))
    except Exception:
        pass
    return usb.backend.libusb1.get_backend()        # 没有则走系统 libusb（本机 brew 没装 → 会 NoBackendError）


def find_all():
    import usb.core
    be = backend()
    return [(d.idProduct, d) for d in usb.core.find(find_all=True, idVendor=VENDOR, backend=be)]


def find_one(pids):
    for pid, d in find_all():
        if pid in pids:
            return pid, d
    return None, None


class MockSenser:
    """离线假相机：把帧当成真机去处理，块设备直接拿固件包里的真镜像。
    用法：`--mock`（默认根 work/mock）。验证 framing / 状态码 / 流式 dump / L1 包不需要接相机。"""

    PKG_DEV = os.path.join(ROOT, 'firmware.tar_unpacked', '0700_part_image', 'dev')

    def __init__(self, root, verbose=False):
        self.root = root
        self.verbose = verbose
        self.sel_path = None
        os.makedirs(os.path.join(root, 'jiritsu'), exist_ok=True)
        os.makedirs(os.path.join(root, 'fs'), exist_ok=True)
        seed = {'libJit.so': open(os.path.join(ROOT, 'tools', 'jit_worker', 'libJit.so'), 'rb').read()
                if os.path.exists(os.path.join(ROOT, 'tools', 'jit_worker', 'libJit.so')) else b'\x7fELF',
                'tmmc.jit': b'', 'DIAC.csv': b'# mock diac\n', 'ver.txt': b'2.00\n', 'jcount': b'3\n'}
        for n, b in seed.items():
            p = os.path.join(root, 'jiritsu', n)
            if not os.path.exists(p):
                open(p, 'wb').write(b)
        # 机身侧配置（FileControl 可读）—— 能拿固件包里的真东西就拿真的，该包没有的就按已验编码合成
        PKG = os.path.join(ROOT, 'firmware.tar_unpacked')
        src = {   # '机身路径' : (包内相对路径, 合成字节)
            '/setting/partinf.conf': ('0300_partconf/partinf.conf', None),
            '/setting/mount.conf': ('0100_config/mount.conf', None),
            '/setting/kemco.txt': ('0800_appli/setting/kemco.txt', None),
            '/version.txt': ('0700_part_image/dev/nflasha7_unpacked/version.txt', None),
            '/setting/updater/dat4': (None, b'\x00\x02'),      # 版本 2.00 = 文本 "0200" 的小端 BCD
            '/setting/updater/comp': (None, b''),              # 2.00 干净状态应为 0 B
            '/mnt/dat2': (None, bytes.fromhex('19000391')),    # 机型码 91030019（小端）
            '/mnt/dat3': (None, b'\x00\x00\x00\x00'),          # region 0
        }
        # mock 的「USB 设备描述符」：preflight 第①项在 --mock 下读这个文件（想模拟身份不符就改它）
        _desc = os.path.join(root, 'device_desc.tsv')
        if not os.path.exists(_desc):
            with open(_desc, 'w') as f:
                f.write('idVendor\t0x054c\nidProduct\t0x0d29\nbcdDevice\t0x0200\nproduct\tILCE-7C\n')
        for pth, (rel, blob) in src.items():
            dst = os.path.join(root, 'fs', pth.lstrip('/').replace('/', '_'))
            if os.path.exists(dst):
                continue
            data = None
            if rel:
                f = os.path.join(PKG, rel)
                if os.path.isfile(f):
                    data = open(f, 'rb').read()
            if data is None:
                data = blob
            open(dst, 'wb').write(data)

    def _jpath(self, path):
        p = path.replace('\\', '/')
        if p.startswith('/tmp/jiritsu/'):
            p = p[len('/tmp/jiritsu/'):]
        return os.path.normpath(os.path.join(self.root, 'jiritsu', p.lstrip('/')))

    def _fpath(self, path):
        if path.startswith('/dev/'):
            dev = path[5:]
            for cand in (os.path.join(self.root, 'dev', dev + '.bin'),
                         os.path.join(self.root, 'dev', dev),
                         os.path.join(self.PKG_DEV, dev)):
                if os.path.isfile(cand):
                    return cand
            return None
        return os.path.join(self.root, 'fs', path.lstrip('/').replace('/', '_'))

    def sendSenserPacket(self, pFunc, data, oData=None):
        if self.verbose:
            print(f'  [mock] PFUNC 0x{pFunc:04x} len={len(data)} {hx(data, 24)}')
        if pFunc == 0x40:
            block, code = struct.unpack_from('<HH', data, 0)
            body = data[4:]
            if block != 0x1001:
                return 2, struct.pack('<I', 0x10000011)
            if code == 15:                                  # SET_FILE_PATH：mode 字节 + 路径
                self.sel_path = body[1:].split(b'\0')[0].decode('latin1')
                return 0, struct.pack('<I', 0)
            if code in (2, 4, 13):                          # MOUNT / START / GET_VERSION
                return 0, struct.pack('<I', 0) + b'mock-1.0\0'
            if code == 17:                                  # GET_FILE2
                if not self.sel_path:
                    return 1, struct.pack('<I', 0x10000009)
                p = self._jpath(self.sel_path)
                if not os.path.isfile(p):
                    return 0, struct.pack('<I', 0) + b''
                return 0, struct.pack('<I', 0) + open(p, 'rb').read()
            if code == 16:                                  # SET_FILE2：mode,id,flag + 内容
                if not self.sel_path:
                    return 1, struct.pack('<I', 0x10000009)
                p = self._jpath(self.sel_path)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, 'wb').write(body[3:])
                return 0, struct.pack('<I', 0)
            if code == 18:                                  # DELETE2
                p = self._jpath(self.sel_path or '')
                try:
                    os.remove(p)
                except Exception:
                    return 0, struct.pack('<I', 0x10000009)
                return 0, struct.pack('<I', 0)
            return 0, struct.pack('<I', 0)
        if pFunc == 0xff01:
            cmd, nsize = struct.unpack_from('<HH', data, 0)
            fn = data[4:4 + nsize].split(b'\0')[0].decode('latin1')
            payload = data[4 + nsize:]
            p = self._fpath(fn)
            if p is None:
                return 0, b''
            if cmd == 2:
                if not os.path.isfile(p):
                    return 0, b''
                blob = open(p, 'rb').read()
                # 故障注入：MOCK_TRUNC_READ=N ⇒ FileControl 读少返回 N 字节（模拟部分写/读回截短）
                _short = int(os.environ.get('MOCK_TRUNC_READ', '0'))
                if _short:
                    blob = blob[:max(0, len(blob) - _short)]
                if oData is not None:
                    oData.write(blob)
                    return 1, None
                return 1, blob
            if cmd == 1:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, 'wb').write(payload)
                return 1, b''
            if cmd == 3:
                try:
                    os.remove(p)
                    return 1, b''
                except Exception:
                    return 0, b''
            return 0, b''
        if pFunc == 0xff03:
            base, size = struct.unpack_from('<II', data, 0)
            blob = b'\0' * min(size, 1 << 20)
            if oData is not None:
                oData.write(blob)
                return 1, None
            return 1, blob
        return 1, b''


class MockCam:
    """与 pmca 的 SonySenserCamera 局部同形（只用到 _sendFileControlPacket）。"""

    def __init__(self, s):
        self.s = s

    def _sendFileControlPacket(self, cmd, filename, data=b'', outFile=None):
        fn = filename.encode('latin1')
        # ★ bug 修正（2026-10-23 真机）：原来写的是 (4 - len%4)，len 已 4 对齐时会多补 4 个 NUL，
        #   相机侧把多余的 NUL 当成路径的一部分 ⇒ 一律回 "file control error 130"。
        #   正确写法是补到 4 的倍数（已对齐就不补）。修好后 FileControl/MemoryDump 全线可用：
        #   /usr/bin/{crypter.elf,udtrbody.bin,up.sh,sen.elf}、/usr/lib/libupdater*.so、/usr/lib/libJiritsu.so 都能读。
        fn += b'\0' * ((-len(fn)) % 4)
        resp, out = self.s.sendSenserPacket(0xff01, struct.pack('<HH', cmd, len(fn)) + fn + data, outFile)
        if resp != 1:
            raise Exception(f'（mock）FileControl 错误 response={resp} path={filename}')
        return out


def connect(args):
    if getattr(args, 'mock', None):
        s = MockSenser(args.mock_dir or args.mock, verbose=args.verbose)
        print(f'mock 模式（根 {args.mock_dir or args.mock}；/dev/* 回退到固件包里的真镜像）', file=sys.stderr)
        return Jiritsu(None, s, MockCam(s), verbose=args.verbose, pad=getattr(args, 'pad', 'pmca'))
    import usb.util
    from pmca.usb.driver.generic import GenericUsbDriver
    from pmca.usb.driver.generic.libusb import UsbBackend
    from pmca.usb.sony import SonySenserAuthDevice, SonySenserDevice, SonySenserCamera

    msc_pids = [int(x, 0) for x in args.msc_pid.split(',')] if args.msc_pid else MSC_PIDS
    svc_pids = [int(x, 0) for x in args.svc_pid.split(',')] if args.svc_pid else SVC_PIDS

    pid, dev = find_one(svc_pids)
    if dev is None:
        pid, msc = find_one(msc_pids)
        if msc is None:
            pids = [p for p, _ in find_all()]
            if pids:
                raise SystemExit('看不到相机。当前 054C PID: ' +
                                 ', '.join(f'0x{p:04X}({MODE_HINT.get(p, "?")})' for p in pids) +
                                 '（相机 USB 模式不对？菜单里改成「大容量存储」）')
            raise SystemExit('看不到任何 054C 设备（线/电源/USB 模式？）')
        msc.default_timeout = args.usb_timeout
        print(f'MSC 0x{pid:04x} 鉴权…')
        auth = SonySenserAuthDevice(GenericUsbDriver(UsbBackend(msc)))
        auth.start()
        auth.authenticate()
        usb.util.dispose_resources(msc)
        t0 = time.time()
        while time.time() - t0 < args.wait_service:
            pid, dev = find_one(svc_pids)
            if dev:
                break
            time.sleep(0.5)
        if dev is None:
            raise SystemExit(f'鉴权后 {args.wait_service}s 内没等到服务模式 PID {["0x%04x" % p for p in svc_pids]}')
        print(f'  服务模式 0x{pid:04x} 已出现')
    else:
        print(f'已在服务模式 0x{pid:04x}')
    dev.default_timeout = args.usb_timeout
    auth = SonySenserAuthDevice(GenericUsbDriver(UsbBackend(dev)))
    auth.start()
    auth.authenticate()
    print('  服务通道鉴权 OK')
    sdev = SonySenserDevice(auth.driver)
    return Jiritsu(auth, sdev, SonySenserCamera(sdev), verbose=args.verbose, pad=getattr(args, 'pad', 'pmca'))


# ---------- 子命令 ----------
def vfat_probe(path, limit=4 << 20):
    """刚 dump 完就地扫一遍：目录项里有没有我们关心的名字（nflasha1 的关键证据）。
    vfat 短名存 'NAME    EXT'，LFN 存 UTF-16LE —— 两种都扫。只做字节扫描，不解文件系统。"""
    want = ['dat1', 'dat2', 'dat3', 'dat4', 'chassis', 'partinf', 'udtrbody', 'updater',
            'jinit', 'libjit', 'tmmc', 'diac', 'udtrmain', 'loader']
    try:
        data = open(path, 'rb').read(limit)
    except Exception:
        return
    hits = []
    for n in want:
        pats = [n.upper()[:8].ljust(8).encode()]
        if len(n) > 8:
            pats.append(n.upper().encode()[:11])
        pats.append(n.encode('utf-16-le')[:12])
        for p in pats:
            i = data.find(p)
            if i >= 0:
                hits.append(f'{n}@0x{i:x}')
                break
    head = data[:96]
    fs = 'FAT' if (head[54:57] == b'FAT' or head[82:85] == b'FAT') else '非-FAT'
    print('    fs=' + fs + '  名字命中: ' + (', '.join(hits) if hits else '无'))


def cmd_scan(args):
    try:
        items = find_all()
    except Exception as e:
        raise SystemExit(f'USB 扫描失败（pyusb/libusb 装好了吗？）：{type(e).__name__}: {e}')
    if not items:
        print('没有 054C 设备')
        return
    for pid, d in items:
        print(f'  054C:{pid:04X}  bus={d.bus} addr={d.address}  {MODE_HINT.get(pid, "?")}')


def cmd_frames(args):
    """离线打印将要上线的帧（不需要相机、不需要 pyusb）——用来自查 framing。"""
    for spec in args.spec:
        kind, _, arg = spec.partition('=')
        if kind == 'jir':
            code = int(arg.split(':')[0], 0)
            tail = bytes.fromhex(arg.split(':')[1]) if ':' in arg else b''
            frame = struct.pack('<HH', 0x1001, code) + tail
        elif kind == 'sel':
            frame = struct.pack('<HH', 0x1001, 15) + b'\0' + arg.encode() + b'\0'
        elif kind == 'w16':
            p, _, f = arg.partition(':')
            blob = open(f, 'rb').read() if f else b''
            frame = struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + blob
        elif kind == 'r17':
            frame = struct.pack('<HH', 0x1001, 17) + b'\0\xff\0'
        elif kind == 'fc':
            cmdb, _, p = arg.partition(':')
            fn = p.encode()
            fn += b'\0' * ((-len(fn)) % 4)   # 同上：已 4 对齐时不要多补
            frame = struct.pack('<HH', int(cmdb, 0), len(fn)) + fn
        else:
            raise SystemExit(f'未知帧类型 {kind}（可用 jir=/sel=/w16=/r17=/fc=）')
        print(f'{spec}\n  PFUNC 0x{0x40 if kind != "fc" else 0xff01:04x}  len={len(frame)}\n  {frame[:64].hex()}{"…" if len(frame) > 64 else ""}')


def cmd_jir(args):
    # 兼容 0x4003 这种“完整 opcode”写法（本项目笔记里习惯写 0x4002/0x4011…）：归一到 Jiritsu code
    if 0x4000 <= args.code <= 0x40ff:
        args.code -= 0x4000
    allow = getattr(args, 'allow_danger', False) or getattr(args, 'know', False)
    if args.code in DANGER_OPCODES and not allow:
        raise SystemExit(f'拒绝 jir 0x40{args.code:02x} {CODES.get(args.code, "")}：危险 opcode 黑名单硬挡，'
                         f'要发必须 --i-know-what-im-doing')
    j = connect(args)
    try:
        j.jir(args.code, bytes.fromhex(args.payload) if args.payload else b'', allow_danger=allow)
    finally:
        j.stop()


def cmd_mount(args):
    j = connect(args)
    try:
        j.jir(2)
    finally:
        j.stop()


def cmd_ls(args):
    j = connect(args)
    try:
        j.sel(args.path)
        resp, st, out = j.jir(17, b'\0\xff\0')
        if out:
            sys.stdout.buffer.write(out)
            if not out.endswith(b'\n'):
                print()
    finally:
        j.stop()


def cmd_get(args):
    j = connect(args)
    try:
        resp, st, out = j.read2(args.remote)
        if args.out == '-' or not args.out:
            sys.stdout.buffer.write(out)
        else:
            open(args.out, 'wb').write(out)
            print(f'  写 {args.out}: {len(out)} B  sha256={hashlib.sha256(out).hexdigest()[:16]}…')
    finally:
        j.stop()


def cmd_put(args):
    gate_write(args, args.remote, 'put(SET_FILE2)')
    j = connect(args)
    try:
        blob = open(args.local, 'rb').read()
        if not args.allow_danger and args.remote.endswith('libJit.so'):
            print(f'  注意：目标 {args.remote} ⇒ 会触发 dlopen（这是部署 worker 的正常做法）')
        resp, st, out = j.write2(args.remote, blob)
        print(f'  SET_FILE2 {args.remote} {len(blob)} B -> response={resp} status={st if st is None else hex(st)}')
    finally:
        j.stop()


def cmd_del(args):
    risky = args.remote.endswith('/') or any(c in args.remote for c in '*?[')
    if risky and not getattr(args, 'allow_danger', False):
        raise SystemExit(f'拒绝 DELETE2 {args.remote}：'
                         + ('末尾带 / ⇒ 递归删' if args.remote.endswith('/') else '含 * ? [ ⇒ glob 会展开')
                         + '（确认就加 --allow-danger）')
    gate_write(args, args.remote, 'del(DELETE2)')
    j = connect(args)
    try:
        resp, st, out = j.delete2(args.remote, mode=args.mode)
        print(f'  DELETE2 {args.remote} -> response={resp} status={st if st is None else hex(st)}'
              + ('  ⚠ 递归/通配已执行' if risky else ''))
    finally:
        j.stop()


def cmd_padtest(args):
    """A/B 判定 FileControl 补白语义：同一路径用两种 padding 各读一次。
    只能用 len%4==0 且内容已知的路径（默认 /usr/bin/sen.elf = 16 B）——两种语义只在这种长度下分叉。
    ⚠真机上这会建立两次会话；鉴于相机 MSC 状态机脆弱，只跑一次、不要反复。"""
    path = args.remote
    print(f'  目标 {path}  len={len(path)} len%4={len(path) % 4} —— '
          + ('两种语义会分叉（有意义）' if len(path) % 4 == 0 else '两种语义等价（白测）：换一条 len%4==0 的路径'))
    for rule in ('pmca', 'aligned'):
        args.pad = rule
        j = None
        try:
            j = connect(args)
            data = j.fread(path) or b''
            print(f'  pad={rule:7} 补白={(4 - len(path) % 4) if rule == "pmca" else ((-len(path)) % 4)}'
                  f'  读到 {len(data)} B  sha={hashlib.sha256(data).hexdigest()[:16]}')
        except Exception as e:
            print(f'  pad={rule:7} 失败: {e}')
        finally:
            if j:
                j.stop()
        time.sleep(1.0)


def cmd_fget(args):
    j = connect(args)
    try:
        if args.out and args.out != '-':
            os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
            tmp = args.out + '.part'
            with open(tmp, 'wb') as f:
                data = j.fread(args.remote, outFile=f)
            os.rename(tmp, args.out)
            size = os.path.getsize(args.out)
            h = hashlib.sha256()
            with open(args.out, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            print(f'  {args.remote} -> {args.out}  {size} B  sha256={h.hexdigest()[:32]}…')
        else:
            data = j.fread(args.remote)
            sys.stdout.buffer.write(data)
    finally:
        j.stop()


def cmd_fput(args):
    note = gate_write(args, args.remote, 'fput(FileControl WRITE)')
    blob = open(args.local, 'rb').read()
    j = connect(args)
    try:
        j.fwrite(args.remote, blob)   # FileControl 写不走 pkt 重试环：只发这一次
        print(f'  FileControl WRITE {args.remote} {len(blob)} B ok  [level={getattr(args, "level", None) or "L2.5"} 白名单备注: {note}]')
        if note.startswith('BOUNDARY'):
            print('  ⚠⚠ 边界探针意外成功：/usr/lib 可写且 zzprobe 已落在里面 —— 非预期结果，停序列(exit 4)待人工确认/清理')
            sys.exit(4)
    finally:
        j.stop()


def cmd_fdel(args):
    gate_write(args, args.remote, 'fdel(FileControl DELETE)')
    j = connect(args)
    try:
        j.fdel(args.remote)
        print(f'  FileControl DELETE {args.remote} ok')
    finally:
        j.stop()


EXPECT = {   # 0300_partconf/partinf.conf（包里自带，权威）—— 读回长度必须等于这个
    'nflasha1': 0x007F0000, 'nflasha2': 0x01400000, 'nflasha3': 0x03000000,
    'nflasha4': 0x00C00000, 'nflasha5': 0x03C00000, 'nflasha6': 0x01000000,
    'nflasha7': 0x00800000, 'nflasha10': 0x00C00000, 'nflasha11': 0x1F400000,
    'nflasha12': 0x02800000, 'nflasha13': 0x00400000, 'nflasha15': 0x12C00000,
    'nflasha16': 0x08C00000, 'nflasha17': 0x06400000, 'nflasha18': 0x01400000,
    'nflasha23': 0x00200000,
}


def _read_once(j, path, out):
    """读一份到 out，返回 (size, sha256)。"""
    tmp = out + '.part'
    with open(tmp, 'wb') as f:
        j.fread(path, outFile=f)
    size = os.path.getsize(tmp)
    h = hashlib.sha256()
    with open(tmp, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    os.rename(tmp, out)
    return size, h.hexdigest()


def _fs_tags(path):
    head = open(path, 'rb').read(2048)
    tags = []
    if head[510:512] == b'\x55\xaa':
        tags.append('MBR55AA')
    if b'FAT16' in head[54:59] or b'FAT32' in head[54:62] or head[0:2] in (b'\xeb\x3c', b'\xeb\x3e'):
        tags.append('FAT')
    if head[1080:1082] == b'\x53\xef':
        tags.append('ext2/3/4')
    if head[:4] == b'WBI1':
        tags.append('WBI1')
    return tags


def read_dev_twice(j, path, out, times=2):
    """★两次独立读才能叫备份（A7C_REAL_DEVICE_FEASIBILITY 的门槛）：同一路径读 N 份、比 sha256。"""
    outs = [out] + [f'{out}.r{i}' for i in range(1, max(1, times))]
    res = []
    for p in outs:
        t0 = time.time()
        size, sha = _read_once(j, path, p)
        res.append((p, size, sha, time.time() - t0))
    for p, size, sha, dt in res:
        print(f'    {p}  {size} B ({size/1048576:.1f} MB) {dt:.1f}s  sha256={sha[:32]}  '
              f'fs={",".join(_fs_tags(p)) or "?"}')
    exp = EXPECT.get(os.path.basename(path))
    if exp and any(r[1] != exp for r in res):
        print(f'    !! 长度与 partinf.conf 不符（期望 {exp}）—— 读不完整，不能当备份')
    if len(res) > 1:
        same = len({r[2] for r in res}) == 1
        print('    ' + ('✓ 两次读 sha256 一致 —— 可以当备份基准' if same else
                        '✗ 两次读不一致：不能当备份！先查 USB 线/供电/口速，再重读'))
    return res[0][1], len({r[2] for r in res}) == 1


def cmd_dump(args):
    """L1/L4 的核心：整分区（或任意文件）读回，流式落盘 + sha256 + fs 指纹 + 两次读自检。"""
    j = connect(args)
    try:
        path = args.dev if args.dev.startswith('/') else f'/dev/{args.dev}'
        out = args.out or (os.path.basename(path) + '.bin')
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        size, same = read_dev_twice(j, path, out, args.twice)
        print(f'  {path} -> {out}  {size} B  多次读一致={same}')
        vfat_probe(out)
        exp = EXPECT.get(os.path.basename(path))
        if exp and size != exp:      # ★长度与 partinf 不符 = 读不完整：判失败（不是只打印警告）
            raise SystemExit(f'dump 失败：{path} 读回 {size} B，partinf.conf 期望 {exp} B —— 不是完整读，不能当备份')
        if args.twice > 1 and not same:
            raise SystemExit(f'dump 失败：{path} 多次读 sha256 不一致 —— 不能当备份')
    finally:
        j.stop()


def cmd_l1(args):
    """L1 只读阶梯包：Jiritsu 区全套 + 关键配置 + （可选）整分区 dump。全部只读。"""
    j = connect(args)
    d = args.dir
    os.makedirs(d, exist_ok=True)
    try:
        print('[1] MOUNT(0x4002)…（SET_FILE2 也能自己挂，这一步只是为了看清挂载状态）')
        j.jir(2)
        print('[2] Jiritsu 区文件（GET_FILE2 0x4011）')
        for name in [x for x in args.files.split(',') if x]:
            p = f'/tmp/jiritsu/{name}'
            resp, st, out = j.read2(p)
            fn = os.path.join(d, name)
            with open(fn, 'wb') as f:
                f.write(out)
            print(f'  {p:34s} {len(out):>8} B  resp={resp} st={st if st is None else hex(st)}  '
                  f'sha256={hashlib.sha256(out).hexdigest()[:16]}')
        print('[3] 机身侧配置（FileControl 0xff01 读）')
        for p in [x for x in args.cfg.split(',') if x]:
            try:
                data = j.fread(p)
                fn = os.path.join(d, 'cfg_' + p.replace('/', '_'))
                open(fn, 'wb').write(data)
                print(f'  {p:34s} {len(data):>8} B -> {fn}')
            except Exception as e:
                print(f'  {p:34s} 读失败 {type(e).__name__}: {e}')
        if args.dump:
            print('[4] 整分区 dump（只读，默认两次独立读）—— 默认含 nflasha1：那 8MB 固件包里根本没有，'
                  'dat2/dat3/boot/{vmlinux,initrd,kemco,loadaddr}/p1chksum（机型/区域身份 + 可能的验签）全在那块里')
            for dev in args.dump.split(','):
                path = dev if dev.startswith('/') else f'/dev/{dev}'
                out = os.path.join(d, os.path.basename(path) + '.bin')
                try:
                    print(f'  {path}')
                    read_dev_twice(j, path, out, args.twice)
                    vfat_probe(out)
                except Exception as e:
                    print(f'  {path} 失败 {type(e).__name__}: {e}')
    finally:
        j.stop()
    print(f'\n产物在 {d}/ —— 逐个 sha256 记进笔记，再进下一级阶梯。')


def cmd_raw(args):
    pf = int(args.pfunc, 0)
    payload = bytes.fromhex(args.payload) if args.payload else b''
    if pf == 0x40 and len(payload) >= 4:
        code = struct.unpack_from('<H', payload, 2)[0]
        if 0x4000 <= code <= 0x40ff:
            code -= 0x4000
        if code in DANGER_OPCODES and not getattr(args, 'know', False):
            raise SystemExit(f'拒绝 raw：载荷命中危险 opcode 0x40{code:02x} {CODES.get(code, "")} —— 必须 --i-know-what-im-doing')
    if pf == 0xff01 and len(payload) >= 4 and struct.unpack_from('<H', payload)[0] == 1:
        nsize = struct.unpack_from('<H', payload, 2)[0]
        gate_write(args, payload[4:4 + nsize].split(b'\0')[0].decode('latin1'), 'raw(FileControl WRITE)')
    j = connect(args)
    try:
        resp, out = j.pkt(pf, payload, retries=0)   # raw 单发：里面可能是写，不重试
        print(f'  response={resp} len={len(out)} {hx(out, 64)}')
    finally:
        j.stop()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def cmd_preflight(args):
    """六项开工自检。任一不符 => 退出码非 0 并说明是哪项。支持 --mock（用本地文件模拟机身路径）。"""
    fails, warns = [], []
    mock = bool(getattr(args, 'mock', None))
    root = (args.mock_dir or 'work/mock') if mock else None
    if mock and not os.path.isabs(root):
        root = os.path.join(ROOT, root)
    print('== preflight ==')

    # ① 设备身份：054c:0d29 + bcdDevice=0x200 + product ILCE-7C
    m = None
    if mock:
        m = MockSenser(root)
        d = {}
        try:
            for line in open(os.path.join(root, 'device_desc.tsv')):
                k, _, v = line.partition('\t')
                d[k.strip()] = v.strip()
        except OSError:
            fails.append('[1] mock 缺 device_desc.tsv（mock 设备描述被删了？）')
        try:
            got = (int(d.get('idVendor', '0'), 0), int(d.get('idProduct', '0'), 0),
                   int(d.get('bcdDevice', '0'), 0), d.get('product', ''))
        except ValueError:
            got = (None, None, None, d.get('product', ''))
        print(f'[1] 设备身份(mock): {got[0]:04x}:{got[1]:04x} bcdDevice=0x{got[2] or 0:04x} product={got[3]!r}')
        if got != EXP_DEV:
            fails.append('[1] 设备身份不符：期望 054c:0d29 bcdDevice=0x0200 product=ILCE-7C '
                         f'（0d2a 是 MTP，Senser 服务不通；bcd 0x203 是 2.03 机的东西）')
    else:
        try:
            pid, dev = find_one([0x0D29])
        except Exception as e:
            pid, dev = None, None
            fails.append(f'[1] USB 扫描失败：{type(e).__name__}: {e}')
        if dev is None and pid is None and not fails:
            fails.append('[1] 没看到 054c:0d29（相机不在 MSC/ILCE-7C 模式？MTP 0d2a 不算）')
        elif dev is not None:
            try:
                prod = dev.product or ''
            except Exception:
                prod = ''
            got = (0x054C, pid, dev.bcdDevice, prod)
            print(f'[1] 设备身份: 054c:{pid:04x} bcdDevice=0x{dev.bcdDevice:04x} product={prod!r}')
            if got != EXP_DEV:
                fails.append('[1] 设备身份不符：期望 054c:0d29 bcdDevice=0x0200 product=ILCE-7C，'
                             f'实到 054c:{pid:04x} bcd=0x{dev.bcdDevice:04x} product={prod!r}')

    def rd(path):
        """机身路径读一份；读不到返回 None。"""
        if mock:
            p = m._fpath(path)
            if p and os.path.isfile(p):
                return open(p, 'rb').read()
            return None
        try:
            return PF_J.fread(path)
        except Exception:
            return None

    PF_J = connect(args) if not mock else None
    try:
        # ② 固件版本：dat4 == 00 02；comp == 0 B；a7 /version.txt 读到更好，读不到只 warn
        dat4 = rd('/setting/updater/dat4')
        if dat4 != b'\x00\x02':
            fails.append(f'[2] dat4={dat4.hex() if dat4 is not None else "读不到"} != 00 02（期望固件 2.00；2.03 会是 00 03）')
        else:
            print('[2] /setting/updater/dat4 = 00 02 ✓（FW 2.00）')
        comp = rd('/setting/updater/comp')
        if comp is None:
            fails.append('[2] /setting/updater/comp 读不到（期望存在且 0 B）')
        elif comp:
            fails.append(f'[2] /setting/updater/comp = {len(comp)} B，应为 0 B（有更新残留，先处理）')
        else:
            print('[2] /setting/updater/comp = 0 B ✓')
        ver = rd('/version.txt')
        if ver is None:
            warns.append('[2] warn: a7 /version.txt 读不到 —— 不算失败，但少一个版本旁证')
        else:
            print(f'[2] /version.txt = {ver[:40].strip()!r}（旁证已读，sha256={hashlib.sha256(ver).hexdigest()[:16]}…）')

        # ③ 工具自身 sha256 必须与 work/TOOL_HASH 一致
        if not os.path.isfile(TOOL_HASH_FILE):
            fails.append('[3] work/TOOL_HASH 不存在（生成：sha256sum tools/jiritsu_send.py > work/TOOL_HASH 再加时间戳）')
        else:
            want = open(TOOL_HASH_FILE).read().split()[0].strip().lower()
            got = _sha256_file(os.path.join(ROOT, 'tools', 'jiritsu_send.py'))
            if want != got:
                fails.append(f'[3] 工具 sha 不符：TOOL_HASH={want[:16]}… 当前 jiritsu_send.py={got[:16]}… '
                             f'—— 工具在清单生成后被改（或被改坏）；确认 diff 后重新生成 TOOL_HASH')
            else:
                print(f'[3] 工具 sha256={got[:16]}… 与 work/TOOL_HASH 一致 ✓')

        # ④ 备份清单存在，且要动的分区在清单里
        if not os.path.isfile(MANIFEST_FILE):
            fails.append('[4] work/BACKUP_MANIFEST.tsv 不存在 —— 先建备份清单再开工')
        else:
            rows = [ln.rstrip('\n').split('\t') for ln in open(MANIFEST_FILE) if ln.strip() and not ln.startswith('#')]
            have = {r[0] for r in rows}
            bad = sum(1 for r in rows if 'LENGTH-MISMATCH' in '\t'.join(r))
            unst = sum(1 for r in rows if 'CONTENT-UNSTABLE' in '\t'.join(r))
            print(f'[4] BACKUP_MANIFEST.tsv：{len(rows)} 行，LENGTH-MISMATCH={bad} CONTENT-UNSTABLE={unst}')
            if bad:
                warns.append(f'[4] warn: 清单里有 {bad} 条 LENGTH-MISMATCH（多为固件包内短副本）——mock/包回退副本不可当备份')
            want_devs = [x.strip() for x in (args.devs or '').split(',') if x.strip()]
            missing = [dv if dv.startswith('nflash') else 'nflash' + dv for dv in want_devs if (dv if dv.startswith('nflash') else 'nflash' + dv) not in have]
            if missing:
                fails.append(f'[4] 要动的分区不在备份清单里：{", ".join(missing)} —— 先 dump 并登记进 BACKUP_MANIFEST.tsv')
            elif want_devs:
                print(f'[4] 要动的分区都在清单里：{", ".join(want_devs)} ✓')

        # ⑤ /setting/updater/ 不能有 mode 旗标（mode, mode1..mode6）
        flags = [p for p in ['/setting/updater/mode'] + [f'/setting/updater/mode{i}' for i in range(1, 7)]
                 if rd(p) is not None]
        if flags:
            fails.append('[5] 检测到 updater mode 旗标残留：' + ', '.join(flags) +
                         ' —— 先跑机身侧 /usr/bin/us_remove_modes.sh（= rm -f /setting/updater/mode*），再重跑 preflight')
        else:
            print('[5] /setting/updater/mode* 无残留 ✓')

        # ⑥ 模式声明：默认 RO；写要 --allow-write（+ --level 在级别表里）
        if getattr(args, 'allow_write', False):
            lvl = getattr(args, 'level', None) or 'L2.5'
            if lvl not in WRITE_WHITELIST:
                fails.append(f'[6] --allow-write 但 --level {lvl} 不在级别表（现有：{", ".join(WRITE_WHITELIST)}）')
            else:
                print(f'[6] 本次声明：RW（--allow-write，level={lvl}，白名单 {len(WRITE_WHITELIST[lvl])} 条）')
        else:
            print('[6] 本次声明：RO（默认）—— 写类子命令会被门禁拒绝')
    finally:
        if PF_J:
            PF_J.stop()

    for w in warns:
        print('  ' + w)
    if fails:
        print('\nPREFLIGHT FAIL:')
        for f in fails:
            print('  ' + f)
        sys.exit(1)
    print('PREFLIGHT PASS')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split('约定：')[1].split('依赖：')[0])
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('--msc-pid', help='逗号分隔的 MSC PID（默认 0x0E8A,0x0D95,0x0D96,0x0994）')
    ap.add_argument('--svc-pid', help='逗号分隔的服务模式 PID（默认 0x0336,0x02A9）')
    ap.add_argument('--pad', choices=['pmca', 'aligned'], default='pmca',
                    help='FileControl 名字字段补白：pmca=`4-len%%4`（pmca/camtool 实机用的那份）或 aligned=`(-len)%%4`（已对齐不补）；'
                         'len%%4!=0 时两者完全等价，所以常规路径不受影响')
    ap.add_argument('--usb-timeout', type=int, default=15000)
    ap.add_argument('--wait-service', type=int, default=90)
    ap.add_argument('--allow-danger', action='store_true', help='允许 FORMAT/FIRMUP/DEBUG/DELETE2-递归 等（危险 opcode 也可用 --i-know-what-im-doing）')
    ap.add_argument('--allow-write', action='store_true', help='打开写门禁（fput/put/del/fdel）；路径还必须在 --level 白名单内，否则默认 RO 拒绝')
    ap.add_argument('--level', default=None, help='写白名单级别（默认 L2.5；现有级别见 tools/jiritsu_send.py 的 WRITE_WHITELIST）')
    ap.add_argument('--i-know-what-im-doing', dest='know', action='store_true',
                    help='硬挡的 0x4003/0x4004/0x4005/0x4006 强行发送（会打印警告）')
    ap.add_argument('--mock', action='store_const', const='work/mock', default=None,
                    help='离线演练：不接相机，用 work/mock 当 Jiritsu 区（/dev/* 回退到包里的真分区镜像））')
    ap.add_argument('--mock-dir', help='配合 --mock 换演练根目录')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('scan', help='列出 054C 设备与 PID 含义').set_defaults(fn=cmd_scan)
    f = sub.add_parser('frames', help='离线打印帧（不接相机、不装 pyusb 也能用）')
    f.add_argument('spec', nargs='+', help='jir=16:00ff00 | sel=/tmp/jiritsu/libJit.so | w16=path:file | r17=path | fc=2:/dev/nflasha15')
    f.set_defaults(fn=cmd_frames)
    j = sub.add_parser('jir', help='发一条 Jiritsu 命令（code + hex 载荷）')
    j.add_argument('code', type=lambda x: int(x, 0))
    j.add_argument('payload', nargs='?', default='')
    j.add_argument('--allow-danger', action='store_true', default=argparse.SUPPRESS)
    j.add_argument('--i-know-what-im-doing', dest='know', action='store_true', default=argparse.SUPPRESS)
    j.set_defaults(fn=cmd_jir)
    sub.add_parser('mount', help='Jiritsu MOUNT(0x4002)').set_defaults(fn=cmd_mount)
    l = sub.add_parser('ls', help='读一个路径的内容（GET_FILE2）')
    l.add_argument('path')
    l.set_defaults(fn=cmd_ls)
    g = sub.add_parser('get', help='GET_FILE2(0x4011) 读 Jiritsu 通道文件')
    g.add_argument('remote')
    g.add_argument('out', nargs='?', default='-')
    g.set_defaults(fn=cmd_get)
    p = sub.add_parser('put', help='SET_FILE2(0x4010) 写 Jiritsu 通道文件（写 libJit.so 会触发 dlopen）')
    p.add_argument('remote')
    p.add_argument('local')
    p.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    p.add_argument('--level', default=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_put)
    d = sub.add_parser('del', help='DELETE2(0x4012) —— 末尾 / 递归删、* ? 会 glob 展开')
    d.add_argument('remote')
    d.add_argument('--mode', type=lambda x: int(x, 0), default=0)
    d.add_argument('--allow-danger', action='store_true', default=argparse.SUPPRESS)
    d.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    d.add_argument('--level', default=argparse.SUPPRESS)
    d.set_defaults(fn=cmd_del)
    fg = sub.add_parser('fget', help='FileControl(0xff01) 读任意路径/块设备')
    fg.add_argument('remote')
    fg.add_argument('out', nargs='?', default='-')
    fg.set_defaults(fn=cmd_fget)
    fp = sub.add_parser('fput', help='FileControl(0xff01) 写任意路径')
    fp.add_argument('remote')
    fp.add_argument('local')
    fp.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    fp.add_argument('--level', default=argparse.SUPPRESS)
    fp.set_defaults(fn=cmd_fput)
    fd = sub.add_parser('fdel', help='FileControl(0xff01) 删')
    fd.add_argument('remote')
    fd.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    fd.add_argument('--level', default=argparse.SUPPRESS)
    fd.set_defaults(fn=cmd_fdel)
    pt = sub.add_parser('padtest', help='A/B 判定 FileControl 补白语义（只有 len%4==0 的路径能测出差别）')
    pt.add_argument('remote', nargs='?', default='/usr/bin/sen.elf')
    pt.set_defaults(fn=cmd_padtest, pad='pmca')

    dm = sub.add_parser('dump', help='整分区/设备读回（流式 + sha256 + fs 指纹）')
    dm.add_argument('dev')
    dm.add_argument('out', nargs='?')
    dm.add_argument('--twice', type=int, default=2,
                    help='同一路径独立读几份并比 sha256（默认 2；只有多读一致才配叫备份）')
    dm.set_defaults(fn=cmd_dump)
    l1 = sub.add_parser('l1', help='L1 只读包：/tmp/jiritsu 全套 + 机身配置 +（可选）分区 dump')
    l1.add_argument('--dir', default='work/l1')
    l1.add_argument('--files', default='libJit.so,tmmc.jit,DIAC.csv,ver.txt,jcount,jiritsu.hash,jinit')
    l1.add_argument('--cfg', default='/setting/partinf.conf,/setting/mount.conf,/setting/kemco.txt,'
                                        '/setting/updater/dat4,/mnt/dat2,/mnt/dat3,/version.txt')
    l1.add_argument('--dump', default='nflasha1,nflasha6,nflasha7',
                    help='逗号分隔（只读）。默认 nflasha1(8M,包里没得)/nflasha6(16M)/nflasha7(8M)；想加 nflasha15(300M) 自己写')
    l1.add_argument('--twice', type=int, default=2,
                    help='每个分区独立读几份（默认 2）；大分区（/usr 300MB）想快就 --twice 1')
    l1.set_defaults(fn=cmd_l1)
    r = sub.add_parser('raw', help='发任意 PFUNC + hex 载荷（实验用）')
    r.add_argument('pfunc')
    r.add_argument('payload', nargs='?', default='')
    r.add_argument('--i-know-what-im-doing', dest='know', action='store_true', default=argparse.SUPPRESS)
    r.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    r.add_argument('--level', default=argparse.SUPPRESS)
    r.set_defaults(fn=cmd_raw)
    q = sub.add_parser('preflight', help='六项开工自检（支持 --mock）：设备身份/FW 版本/工具 sha/备份清单/mode 旗标/RO-RW 声明；任一不符退出码非 0')
    q.add_argument('--devs', default='', help='逗号分隔：本次要动的分区（每个必须在 BACKUP_MANIFEST.tsv 里），如 nflasha7,nflasha6')
    q.add_argument('--allow-write', action='store_true', default=argparse.SUPPRESS)
    q.add_argument('--level', default=argparse.SUPPRESS)
    q.set_defaults(fn=cmd_preflight)

    args = ap.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
