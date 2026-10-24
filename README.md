# Sony A7C（ILCE-7C / CXD90045）固件逆向

一台 **ILCE-7C 一代**（SoC = CXD90045，32 位 ARM/armv7，Linux 3.0.27_nl-rt106+）的固件破解预研：
把官方更新包**完整解开**、把更新器/Jiritsu 服务通道的门禁**逐指令读清楚**、把「改哪里能拿到 root、怎么写回、会不会砖」写成可执行的路线图。

本仓库**只提交我自己产出的东西**：分析文档、脚本/工具源码、小体积文本证据（清单、日志、比对结果）。
**固件本体、从固件包里解出来的 Sony 原件、反汇编/字符串/内存转储、第三方 clone 全都不入库**（规则见 `.gitignore`，原因见下面的「不提交的内容」）。
目前阶段 = 纯静态分析 + QEMU 离线跑，**没有对真机做过写入**。

---

## 1. 先读什么（按顺序）

| 文件 | 内容 |
|---|---|
| `FIRMWARE_MOD.md` | 主文档：包格式（UFU/FDAT/UDTRFIRM）、AES 分段解密、四条写回路线（改包重刷 / 服务通道刷 `libJit.so` / 服务模式刷原厂包 / BootROM 串行启动）与各自前提 |
| `TEST_LADDER.md` | 变砖风险模型：哪个分区坏了等于砖、谁能救；「永不碰清单」；安全测试阶梯 L1→L2 |
| `UPDATER_ANALYSIS.md` | 更新器内部机制：`config.xml` → 脚本 → ELF → 分区，以及更新模式旗标 |
| `A7C_REAL_DEVICE_FEASIBILITY.md` | 真机连接与写入可行性的**保守评估**（把「能跑代码」和「能刷进去」分开算风险） |
| `notes/` | 分项深挖：`jiritsu.md`（服务通道协议）、`updater_flow.md`（刷入枚度 / `us_mkfs.sh` 路径）、`updater_verify.md`（272 B 尾到底谁验）、`injection.md`、`qemu.md`、`zve10-qemu.md`（同芯片 ZV-E10 的 QEMU/救援全记录）、`a7c2-tools.md`、`github-survey.md`（同代次公开工作调研）、`camtool.md`、`senser_shell.md`、`toolchain.md` |
| `work/` | 逐项实验的现场：脚本 + 结果笔记（`*.md`）+ 小体积证据（manifest / diff / 串口日志） |

关键结论（细节都在上面这些文件里）：

- 外层容器 `UFU`（IFF 风格分块 + CRC32）→ `FDAT`（1024 B 帧 + 两段 AES，**密钥全部公开**）→ `UDTRFIRM` 明文区里带 `firmware.tar` / `updater.img`，逐字节比对全中。
- 272 B 尾（16 B IV + 256 B blob）：**2.00 上 PC 可达的路径里没有一处真的调 `RSA_verify`**（`sauu` 是死代码；`mf` 到 2.03 才链进验签；只有 MSCRYPT(mode5) 的 SD 卡路径验）。所以「能不能自制包刷回去」不是被签名挡住，而是被 `0x142` 版本门禁和刷入枚度挡住。
- 首选路线是 **B：服务模式 → `SET_FILE2(0x4010)` 直写 `/tmp/jiritsu/libJit.so` → 自己写的 ARM32 载荷在 `.init` ctor 里干活**（同芯片 ZV-E10 已跑通；A7C 一代 2.03 上有第三方 root 实测）。
- 真砖只有 `boot0/boot1`、分区表、`nflasha1/2`；app 分区（a3/5/7/15）写坏了更新器能重建。

## 2. 目录结构

```
FIRMWARE_MOD.md / TEST_LADDER.md / UPDATER_ANALYSIS.md / A7C_REAL_DEVICE_FEASIBILITY.md
config.yaml          # fwtool.py 用的设备描述（机型 0x91030019 / CXD90045 / USB 描述符白名单）
notes/               # 分项深挖文档
tools/               # 我自己写的脚本（下面 §4 有清单）
  jit_worker/        # 给 Jiritsu 通道写的 ARM32 libJit.so 载荷源码（libJit.c / selftest.c / Makefile）
  tests/             # mock 故障回归脚本
work/                # 实验现场：脚本 + .md 结果笔记 + 小文本证据
```

## 3. 不提交的内容（以及怎么拿回来）

`.gitignore` 采用「默认全忽略、按类型放行文本」的白名单写法。**故意排除**的东西：

| 类别 | 具体 | 为什么不入库 |
|---|---|---|
| Sony 固件容器 | `FirmwareData_ILCE7CV200.dat` / `...V203.dat` / `FirmwareData_ZVE10V200.dat`（在仓库上一级目录）、`firmware.tar`、`updater.img`、`*.fdat`、`nflasha*` | Sony 专有二进制，不重分发；体积也大（单个 330–363 MB，超 GitHub 100 MB 上限） |
| 解包出来的 Sony 原件 | `firmware.tar_unpacked/`、`updater.img_unpacked/`、`ZVE10/`、`work/v203/{a1_initrd,body200,body203,n15,u203}/`、`work/l1-camera/a*_extracted*/`、mock 镜像里的 `fs/` | 那些 `.sh` / `.conf` / LICENSE / 内建数据是 Sony 的版权内容（我只在文档里引用片段） |
| 反汇编 / 字符串 / 内存转储 | `*.asm`、`*.out`、`*.decode`、`strings_*.txt`、`s_all.txt`、`fwdump*/`、`snap_*.txt`、`emmc_*.txt`、`work/cmdlines/` | Sony 机器码的衍生内容 + 体积大；用 `tools/` 里的脚本可离线重现 |
| 第三方仓库 clone | `refs/`（`Sony-PMCA-RE`、`fwtool.py`、`zve10-qemu`、`a7c2-fl23-research`、`CXD90045-FPSU`、`Sony-ZVE-10-Camtool`）、`work/qemu-a7c/qemu-sony*`、`work/sony-src/`（Sony 提供的 GPL 内核源码包）、`dist/`、`.venv-jir/` | 各自上游保有自己的权利；clone 用 `tools/get_thirdparty.sh` 一条命令重建 |
| 二进制产物 | `*.so` `*.ko` `*.elf` `*.bin` `*.tar` `*.uxc` 等 | 由源码或固件生成，不入库 |

### 3.1 固件输入（本机指纹，便于你自己下载后核对）

官方更新器包（Sony 支持站，ILCE-7C / ZV-E10 的 “System Software” 下载）解出来后的 `.dat`：

```
34aeaf5ecad2d6f52e5e37ff334200c2a4c115e9d314cec9af636a41ef521bb3  FirmwareData_ILCE7CV200.dat   (346,206,712 B)
b5c20ed18b656d22611aa0ee0c83c168bd247030dc7bcf249bdb60d1168c3f39  FirmwareData_ILCE7CV203.dat   (363,197,944 B)
7fd81fb3631de5a21b08ef9b7072a83d80085ff14c63e197bf2d501127667da4  FirmwareData_ZVE10V200.dat    (349,456,904 B)
```

从 `.dat` 里再解出来的内层件：

```
5913184ad51f38b82a06bbc3712c73bc0433c14822edb010c57bb4a05e78a289  firmware.tar     (344,709,632 B)
b0b344292be92fea0795870c6b7a6428de3659383d26029825f65c58a6ead9bb  updater.img      (  143,360 B)
611042f790ba21422e7c6b6185781f9af748143b3d8010b2aea4591f15202eb3  nflasha3.bin     (/system 分区镜像，包内)
96ffa37a0dd1571271ebbaff9160eb2f6723db5a86c72b08ac26d2ae8b14fa31  ZVE10/firmware.tar
```

解包/解密的入口脚本（都在 `tools/`，只依赖 python3 + `pycryptodome` + `capstone`）：

```sh
python3 tools/ufu_scan.py     <FirmwareData_*.dat>        # 列 UFU 分块、校 DEND CRC32、解 UDID 白名单
python3 tools/fdat_unwrap.py  <FirmwareData_*.dat> ...    # FDAT 去帧 + AES-128-ECB + 帧校验验证
python3 tools/fdat_aescbc.py  <FirmwareData_*.dat> out    # 完整两段 AES（ECB + 256-CBC）解密
python3 tools/fdat_layout.py  out                         # UDTRFIRM 布局 + 与包内 updater.img/firmware.tar 逐字节比对
python3 tools/fdat_hdr_edit.py <FirmwareData_*.dat> ...    # 只改身份字段（版本/机型/区域）的最小重打包
```

（`refs/fwtool.py` 也能解：`config.yaml` 就是给它用的 A7C 设备描述。注意 CXD90045 的多把 FDAT 密钥在 `fwtool.py` PR #52 里，master 只有 `k0`。）

### 3.2 第三方参考

```sh
tools/get_thirdparty.sh          # 把 refs/ 重建一遍（浅 clone）
```

清单：`ma1co/Sony-PMCA-RE`、`ma1co/fwtool.py`、`cokeenet/zve10-qemu`、`QAQLeonard/a7c2-fl23-research`、
`Lost-week-1025/CXD90045-FPSU`、`nolan2628/Sony-ZVE-10-Camtool`、`ma1co/qemu`（`hw/arm/bionz.c`，CXD90045 板级模型）。
更多同代次公开工作的对比见 `notes/github-survey.md`。

## 4. `tools/` 里的东西

| 脚本 | 干什么 |
|---|---|
| `ufu_scan.py` `fdat_unwrap.py` `fdat_aescbc.py` `fdat_layout.py` `fdat_hdr_edit.py` `fdat_tail.py` | 官方包格式：分块、解密、布局、最小改包、尾部 272 B 穷举 |
| `jdis.py` `tdis.py` `tdis2.py` `linsweep.py` `talkdis.py` `ufpdis.py` | 自己写的 ARM/Thumb 线性反汇编 + 字面量池/GOT/PLT 语义注释（比 r2 自动注释可靠） |
| `elfdyn.py` `ufpsyms.py` `vtmap.py` `vtable_dump.py` `tbl.py` `adjtbl.py` | ELF32(ARM) 元信息、符号、C++ vtable、TBB/TBH 跳转表 |
| `modescan.py` | 找「更新模式字母 / 模式编号」的比较点 |
| `verify_sums.py` | 复算包内每个 `*.sum` 的 CRC32 + size（对应相机里的 `uc_crc32sum.elf`） |
| `jiritsu_pack.py` `jiritsu_send.py` | Jiritsu 服务通道：FIRMUP(0x4006) tar 载荷构建 / USB 发送 |
| `jit_worker/` | 给 Jiritsu 通道加载的 ARM32 `libJit.so` 载荷源码（干活放在 `.init` ctor，dlopen 即执行） |
| `camuser.sh` `camprefix.sh` | 用**相机自己的用户态**（busybox 1.29.3 / glibc 2.11.2 / armv7）离线跑 ELF：解包丢了符号链接，所以现补 |
| `wrapw.sh`、`tests/` | 本机「写」包装（不重试）与 mock 故障回归 |

## 5. 版权 / 免责

- 本仓库里的文档与脚本（`*.md`、`*.py`、`*.sh`、`tools/jit_worker/*` 等）按 MIT 授权，见 `LICENSE`。
- **不包含** Sony 的固件、镜像、脚本、配置或它们的反汇编/转储；提到 Sony 商标、机型名仅为说明用途。
- 第三方仓库（`refs/`、QEMU、PMCA-RE 等）版权归各自作者，本仓库只保留 URL 与用法说明。
- 所有上机操作风险自担：改固件可能让相机不能启动，而 eMMC 是焊死的。先读 `TEST_LADDER.md` 的「永不碰清单」。
