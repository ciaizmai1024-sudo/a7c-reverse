#!/usr/bin/env python3
"""FileControl WRITE 原始响应探针：打印 resp=... 无论成败（rc：1->0，其它->3，传输错->2）。
载荷构造与 pmca SonySenserCamera._sendFileControlPacket 完全一致（含其补白语义），
只是直接用 Jiritsu.pkt 拿回 response 字节，不被 pmca 的 raise 吞掉。"""
import struct, sys, hashlib
from argparse import Namespace
sys.path.insert(0, '/home/wubin/a7c-jiritsu/tools')
import jiritsu_send as J


def main():
    path, local = sys.argv[1], sys.argv[2]
    ns = Namespace(verbose=False, msc_pid=None, svc_pid=None,
                   usb_timeout=15000, wait_service=90)
    j = J.connect(ns)
    try:
        blob = open(local, 'rb').read()
        fn = path.encode('latin1')
        fn += b'\0' * (4 - len(fn) % 4)          # pmca 语义（真机验证过的补白）
        payload = struct.pack('<HH', 1, len(fn)) + fn + blob
        print(f'  payload head: {payload[:40].hex()}  (cmd=WRITE nameSize={len(fn)} datalen={len(blob)})')
        try:
            resp, out = j.pkt(0xff01, payload, retries=0)
        except Exception as e:
            print(f'  FPUT-RAW EXC {type(e).__name__}: {e}')
            return 2
        print(f'  FPUT-RAW resp={resp} outlen={len(out)} out={out[:64].hex()}')
        return 0 if resp == 1 else 3
    finally:
        j.stop()


if __name__ == '__main__':
    sys.exit(main())
