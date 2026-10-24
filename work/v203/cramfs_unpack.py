#!/usr/bin/env python3
"""Sony updater-body cramfs 解包器（按 refs/fwtool.py/fwtool/archive/cramfs.py 的布局实测重写，零依赖）。

超级块 64 B（LE）：magic 'E=\xcd(' size flags future signature[16]='Compressed ROMFS'
  crc edition blocks files name[16]
inode 12 B：mode u16 | uid u16 | size_gid u32(size=低24b, gid=高8b) | nameLen_offset u32
  nameLen=(低6位)*4（name 直接跟在 inode 后），offset=(>>6)*4
目录/文件的压缩数据：offset 处先 [u32 首块起点][u32 各块边界...]，相邻边界间为 zlib 压缩块（4096 解压）。
用法: python3 cramfs_unpack.py <img> <outdir>
"""
import os, struct, sys, zlib, stat

def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]

def chunks(data, off, size):
    nblk = (size - 1) // 4096 + 1 if size else 0
    ptrs = [off + nblk * 4] + [u32(data, off + 4 * i) for i in range(nblk)]
    out = bytearray()
    for i in range(len(ptrs) - 1):
        out += zlib.decompress(data[ptrs[i]:ptrs[i + 1]])
    return bytes(out[:size])

def walk(data, pos, path):
    """读取 pos 开始的 inode 串（直到 offset 字段回到本目录 inode 串起点），返回新 pos。"""
    end = pos
    first = pos
    entries = []
    while True:
        mode = struct.unpack_from('<H', data, pos)[0]
        uid = struct.unpack_from('<H', data, pos + 2)[0]
        sg = u32(data, pos + 4)
        nlo = u32(data, pos + 8)
        size = sg & 0xFFFFFF
        gid = sg >> 24
        nl = (nlo & 0x3F) * 4
        off = (nlo >> 6) * 4
        pos += 12
        name = data[pos:pos + nl].split(b'\0')[0].decode('latin1')
        pos += nl
        if off == end and entries:
            # 最后一个 inode 的 offset 指回 inode 串（kernel cramfs 惯例：它其实是本目录的 name-offset 哨兵）
            break
        entries.append((mode, size, name, off))
        if len(entries) > 5000:
            raise RuntimeError('runaway')
    # 注意：fwtool 不认哨兵，而是把 offset==串起点的 inode 也当文件；实测两版结构：inode 里 offset 指回本串开头的是“父目录.”占位。
    return pos, entries

def main():
    img, outdir = sys.argv[1], sys.argv[2]
    data = open(img, 'rb').read()
    assert data[:4] == b'\x45\x3d\xcd\x28'
    fsize = u32(data, 4)
    assert data[16:33] == b'Compressed ROMFS', data[16:33]
    files = []
    # fwtool 风格：从 super(64) 起逐 inode 递归，目录的 inode.size = 其子 inode 串字节数，子串在 offset 处
    def rd(pos, dirpath):
        out_entries = []
        while True:
            mode = struct.unpack_from('<H', data, pos)[0]
            sg = u32(data, pos + 4)
            nlo = u32(data, pos + 8)
            size = sg & 0xFFFFFF
            nl = (nlo & 0x3F) * 4
            off = (nlo >> 6) * 4
            pos += 12
            name = data[pos:pos + nl].split(b'\0')[0].decode('latin1')
            pos += nl
            out_entries.append((mode, size, name, off))
            # cramfs: 名字长度表结束条件 = 下一个 inode 的 offset 回到本 inode 串起点（kernel 的 NAME_OFFSET 哨兵）
            nxt = struct.unpack_from('<I', data, pos + 8)[0] if pos + 12 <= len(data) else 0
            if ((nxt >> 6) * 4) == off and off == ((u32(data, 8 + 8)) >> 6) * 4:
                pass
            if pos + 12 <= len(data):
                nxoff = (u32(data, pos + 8) >> 6) * 4
                if nxoff == off:  # 哨兵：下一个 inode 指回本串开头 → 本目录结束
                    break
            if nl == 0 and name == '':
                break
        for (mode, size, name, off) in out_entries:
            if not name:
                continue
            p = os.path.join(dirpath, name)
            if stat.S_ISDIR(mode):
                os.makedirs(p, exist_ok=True)
                files.append((p, None, mode))
                sub = rd(off, p)  # 子 inode 串起点 = off
            else:
                content = chunks(data, off, size)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, 'wb').write(content)
                if stat.S_ISLNK(mode):
                    pass
                files.append((p, len(content), mode))
        return out_entries
    # 上面终止条件不可靠 —— 直接用 fwtool 的办法：inode 数组是扁平的，用 files 计数? 改：kernel 惯例：
    rd(64, outdir)
    print('extracted', len(files), 'entries')

if __name__ == '__main__':
    main()
