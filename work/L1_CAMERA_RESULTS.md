# L1 真机取证结果（远端 Ubuntu 24.04 / wubin@172.22.22.131，2026-xx）

## 流程
- 包：`dist/a7c-jiritsu-linux/` → 远端 `~/a7c-jiritsu/`
- 依赖：`apt-get install usbutils python3-usb python3-pycryptodome`（pyusb 1.2.1-2 / pycryptodome 3.20.0），libusb1 后端可用
- **修了一个包内 bug**：`tools/jiritsu_send.py` 把 `refs/Sony-PMCA-RE` 直接塞进 sys.path，但目录名带连字符不能当包名 →
  `ImportError: attempted relative import beyond top-level package`。改成在 `refs/_pmca_pkg/pmca` 建软链接后
  `sys.path.insert(refs/_pmca_pkg)`，`pmca.usb.sony` 等导入成功。已同步改 `tools/jiritsu_send.py`、
  `dist/a7c-jiritsu-linux/tools/jiritsu_send.py` 并重建 `dist/a7c-jiritsu-linux.tgz`。
- 相机 PID：`054c:0d29`（Mass Storage，序列号 D01660523CD5），dmesg 干净（无 over-current / not accepting address）
- 鉴权：`MSC 0x0d29 鉴权… → 服务模式 0x0336 已出现 → 服务通道鉴权 OK`（每次新进程都会重新鉴权一次）
- 注意：鉴权后相机会在 MSC(0d29)/服务模式(0336) 之间重枚举；空闲一小段时间会退回 MSC，之后 FileControl 仍可用（需在每次调用前重新鉴权）。

## L1（`~/a7c-jiritsu/l1_run.log`）
| 分区 | 大小 | 期望 | sha256（两次读一致 ✓） |
|---|---|---|---|
| nflasha1 | 8,323,072 | ✓ | 82e1b199a8e80531730b220899ff1a1ba9ba91a60d3de7d49a67546959b79a1a |
| nflasha6 | 16,777,216 | ✓ | b9d759a7a09f210f28df1380c7f7758c08d456b6e0cf3ac8f7eccc52875187e8 |
| nflasha7 | 8,388,608 | ✓ | c2b7af2f9f02e57319201af13362e0682c96e3520229a388a5293621d6da6107 |

Jiritsu 区（GET_FILE2 0x4011）全部返回 `status=0x10000006`（ver.txt/tmmc.jit/DIAC.csv/jcount/jiritsu.hash/jinit/libJit.so 都是 0 B）
→ 这台机身的 Jiritsu 通道文件全空（对应「未装/未初始化 hack」）。
FileControl 只读：`/setting/kemco.txt` 1905B、`/setting/updater/dat4` 2B、`/version.txt` 19B（= `39119_05.2021111501`）；
`/setting/partinf.conf`、`/setting/mount.conf`、`/mnt/dat2`、`/mnt/dat3` 一律 `file control error 130`（拒绝），
`fget /boot/p1chksum`、`/boot/dat2`、`/boot/dat3`、`/p1chksum`、`/dat2`、`/dat3` 同样 130。

本机 `work/l1-camera/` 已 `shasum -a 256 -c` 全 OK（SHA256SUMS 路径前缀 `work/l1/` 需 sed 去掉）。

## nflasha1（机身）vs work/v203/nflasha1_203.bin
- 长度相同 8,323,072；前 16 字节相同 `eb3c90 6d6b66732e6661740002200100`（mkfs.fat + BPB）；0x1FE 两边都是 `55aa`（无 MBR 分区表，整个 a1 就是一个 Sony 定制 FAT12 卷）
- 差异 512B 块：**12999 / 16256**，集中在 8 段：
  `0x0-0x5ff`（引导扇区+FSInfo，仅少量字节差）、`0x4200-0x45ff`（FAT 链，只差 4 个 EOF 簇位）、
  `0x8200-0x83ff`（根目录）、`0x10200-0x103ff`（BOOT 子目录）、`0x14200-0x66b7ff`（文件数据区，12895 块）、
  `0x66c200-0x66c7ff`、`0x670200-0x6703ff`、`0x674200-0x6743ff`（机身侧全 0，203 有内容）
- 根目录对比：
  - 机身：`boot/`(dir, cl3) `p1chksum`(105B, cl404) `dat2`(4B, cl405) `dat3`(4B, cl406) —— dat2/dat3 是**出厂镜像里没有**的（创建时间戳 2021-08 前后，属机身运行期生成）
  - 203：只有 `boot/`、`p1chksum`(105B, cl412)
  - `boot/` 子目录（两边同名 4 个文件，尺寸不同）：
    `initrd.img` 机身 4,812,800 / 203 4,943,872；`vmlinux.bin` 机身 1,697,076 / 203 1,701,156；
    `kemco.txt` 1062/1062；`loadaddr.txt` 33/33
- p1chksum（105B）内容两边 sha256 相同（按 203 侧读取；机身侧该簇位置在 0x660000 之后全 0，未对齐到可直接索引的位置，待用块偏移再核）
- 机身 a1 在 `0x660000` 之后**全零**，203 同区间还有 ~47KB(vmlinux 尾) + 3×512B 数据 → 机身 a1 尾部有未写/清零区域

## 只读纪律
只用过 scan / mount / ls / get / fget / dump / l1；没跑 put/fput/del/fdel/wr，没跑官方升级器，没断电。

## 路径
- 远端：`~/a7c-jiritsu/l1_run.log`、`~/a7c-jiritsu/work/l1/`（+ SHA256SUMS）、`~/a7c-jiritsu/work/probe/`、`~/a7c-jiritsu/probe2.sh`、`/tmp/a7c-dmesg.log`
- 本机：`work/l1-camera/`（16 文件，校验通过）
