# R15 POSTMORTEM（Round15 收尾 + Round16 起手）
写在 `~/qemu-a7c/results_round16/R15_POSTMORTEM.md`（同一份副本在本地 `work/qemu-a7c/results/round15/R15_POSTMORTEM.md`）。
注：`p4 BOOT1 RC=0` 是主控 kill，不算"跑完"；本轮有效 run = `t1 t2 p1 p2 p3 p4 p5`（+ 发车的 `p6`）。

## A. 写表（QEMU 侧 `ZZSDWRITE p=0 rel=`，每条 512 B；来源 `hw/sd/sd.c:2126` 的打印）
所有 r15 尝试去重后的**全集只有 11 条**：

| rel(USER 字节偏移) | 落在哪个分区（分区表实测） | 宿主文件偏移(=rel+0x400000) | 是什么 |
|---|---|---|---|
| `0x800200` | index1 = 0x800000 (20 MiB) → guest **`/dev/nflasha2`**（= `/setting` vfat） | `0xc00200` | vfat 引导/FAT/目录区：`mode5` 旗标文件 + `rm -rf mode*` |
| `0x800a00` | 同上 | `0xc00a00` | 同上 |
| `0x810a00` | 同上（a2 内第二簇区） | `0xc10a00` | 同上 |
| `0xb82e000 … 0xb82ee00`（8 条连续） | index10 = 0xb800000 (500 MiB "卡"切片) → guest **`/dev/nflasha11`** | `0xbc2e000 … 0xbc2ee00` | 卡内偏移 `0x2e000` = **vfat 根目录区**（sdfileinput `open()` BODYDATA.DAT 时目录项被搅） |

结论（这条比验签值钱）：
- **mode5 至今没有写过任何固件分区**：a1(0x10000)、a3(0x1C00000)、a10(index9 0xAC00000)、a15、**a23/PMBP(0x50800000)** 全部**零写入**；
  写只有 **a2（旗标区，3 个扇区）** 和 **卡切片自己的目录项（8 个扇区）**。
- 出现规律：`t2/p1/p2`（没走到 UUD 检查）= 3 条（只有 a2）；`p3/p4/p5`（走到 UUD 检查）= 11 条（多出的 8 条＝卡目录项）。
  ⇒ "多写的那 8 个扇区"是**打开卡文件**的副作用，不是 updater 写数据。
- `comp` 旗标（a2 里出厂就有）会在每次 `execute_ufp.sh` 开头 `rm -rf /setting/updater/mode*` ⇒ **`mode5` 必须在每轮开跑前重新注入**（`inject_mode5.sh`，宿主侧写 a2 = 那 3 个 a2 扇区的来源之一）。

### 读量（判断"有没有把 FDAT 喂进摘要"）
`ZZSDREAD`（`sd.c:2118`）去重后：**每次尝试 762–997 个 512 B 扇区 ≈ 0.38–0.51 MB**；
其中落在卡切片内的只有 **136 个扇区 = 69,632 B**（范围 `0xbc00000..0xbc3ae00`，即卡的 FAT/目录 + 文件最前面一小截）；
全局最大读偏移 `0x50c3be00`（那是 R13 的 a23 读探针，不是卡）。
⇒ **读量 ≪ 346 MB ⇒ 整个 FDAT 从没被读，更没有做摘要/验签。**
旁证（不依赖 SD 模型，因为我们的 Fsys 桩走 POSIX/loop 路径、`ZZSDREAD` 看不见它）：
`r15_p5` 里 `R15FSHIM` 的行型统计 = `Open/Seek×5/Mount/FindFirst/Close`，**`Fsys_Read` 调用次数 = 0** ⇒ updater 只做了 5 次 seek（每次读 8 B 记录头，由真 libInfraFsys 的 SD 路径读，见上 136 扇区）就中止。

## B. `Error 42` / `Error 86` 是什么（两处都不是签名，也不是写）
- 打印点：`usr/bin/common.src:74` `echo "[FIRMUP NG] : Error $1"`。`common.src` 的码表只有
  `41 INVALID_FIRMWARE / 45 MPR_ERASE / 47 POWER_IC / 48 FSYS_FORMAT / 54 UINCOMP / 72 NAND_MOUNT / 73 NAND_UNMOUNT / 87 SYSTEM / 99 FATAL`
  ⇒ **42、86 不在 shell 表里**，是 `libsdfileinputupdaterapi.so` 里 `LEDErrorConverter::Convert(ApiException)` 映射出来的用户可见码
  （`ApiException` 的枚举是 `0x3000x` 家族：反汇编里 `mov.w r1,#0x30000` 系列，见 `results_round13/sdpa.asm` 行 4553/7567/7749/7811/8295/8347/8485）。
- **`Error 42`** 紧跟在 `SDUUDConditionChecker.cpp:130 "Firm size is larger than buffer size. chunk_base.length(1347571542) emptyBufferSize(535293952)"` 之后
  ⇒ 抛点＝**UUD 条件检查阶段的"记录/chunk 尺寸合理性"判定**（它把 chunk 头的 `length` 与 510 MiB 解密缓冲比）。
  根因是我们桩的 `Fsys_Seek` 语义错了（见下）导致 chunk 头读出垃圾。
- **`Error 86`**（修好 Seek 之后，`r15_p5`）紧跟在 `SDFileInputUpdaterManager.cpp:178 "not meet UUD conditions (ver, model, etc.)"` 之后
  ⇒ **升级条件门**：日志给了两边信息 —— `SDUUDConditionChecker.cpp:53/54`
  `Old Version:2.0 Model:0x91030019 Region:0x0000` vs `New Version:2.0 Model:0x91030019 Region:0x0000`
  ⇒ **Model/Region 全对上（0x91030019 = ILCE-7C，说明真 `.dat` 的 FDAT 头被正确解析）**，只是**版本相等（QEMU 盘里的固件已经是 2.00）→ 不算升级 → 拒**。
- ★`r15_p5` 里已经出现 **`UdrAPI,…SDUUDConditionChecker.cpp:134,"found FDAT"`** ⇒ 桩修好后链子走到 **FDAT 记录命中**。
- 修法（正对照）：卡上换 **2.03** 的 `FirmwareData_ILCE7CV203.dat`（363,197,944 B，md5 `91507fc258de1fd7e8def8b3a6e4dbe7`，500 MiB 卡放得下）
  → `New 2.03 > Old 2.00` ⇒ 过 UUD 门 ⇒ 才轮到 `SDDecryptorModule`/`VerifySignature`。
  **run `r15_p6` 已发车**（`a7c_emmc_r15v203.img` + `initrd_r15e.img` + `vmlinux_r12.bin`，1800 s）。

## C. 卡切片里的 `.dat`、`mode5`、负样偏移
- **卡切片宿主偏移 = `0xbc00000`**（分区表 index10 `start=0xb800000` + boot 前缀 `0x400000`；主控记的 `0xc000000` 差了一个前缀，按 `0xc000000` 挂会 `wrong fs type`），大小 `0x1f400000` = 500 MiB。
- `a7c_emmc_r15.img` 卡切片里有 **`BODYDATA.DAT` = 346,206,712 B，md5 `058628057a5d73af90c3a232eac8fb66`**（＝官方 2.00 `.dat` 未改一字；guest 侧 `R15FSHIM Open-size v=346206712` 同步证明）。**没有别的文件**（根目录只有它）。
- **`mode5` 旗标不在卡上、也不在 a2 里**：`/setting/updater` 只有 `comp`、`dat4`（`comp` 会删 `mode*`）⇒ 旗标是每轮由 `inject_mode5.sh` 在宿主侧写进 a2（`offset=0xc00000`）的。
- 负样 `a7c_emmc_r15neg.img`：**只在卡切片内**（`0xbc00000..0xdc3fffff`）按 512 B 扫，只有 **2 个扇区**不同：
  1. `0xbc2e000`（vfat 根目录区）—— **不是**我们的翻位，是正样镜像被 guest 跑脏的目录项（`0x21` vs `0x58`）；比较时必须排除；
  2. `0x1bc00000`（我们的翻位）。
  把 neg 的 vfat 挂出来逐字节对文件 ⇒ **文件内第一个不同偏移 = `0xffcc0dc`（268,222,684），`0xde → 0xc3`（1 bit）**。
  判定：FDAT 记录在容器偏移 `0xd4`、payload `0xdc..0x14a2b0ec`、签名＝最后 `0x100`（`0x14a2b0ec..0x14a2b1ec`）
  ⇒ **落点在密文体＝签名消息区内，不在签名区** ✓（正是负对照要的位置）。注：文件偏移 ≠ 卡内 vfat 偏移（簇映射位移 0x34000），所以"文件偏移"必须以挂载后比对为准。
- 实验镜像 md5（guest 每轮会写，会漂）：`a7c_emmc_r15.img` `dd414594a30082e9403a4f178f6e5189`；`a7c_emmc_r15neg.img` `a0696f9014395b8a3b3eb97aec336816`；
  `a7c_emmc_r15v203.img` `c95b9ac078601e5f28b6271aefcfcbdf`（建卡后、跑前）。基线 `a7c_emmc_pt4.img` `8587674613…` 未动。

## 定论（三选一里答 a+b，c 还没到）
- **(a) 卡传输是假的**：没有真 SD 卡；卡＝eMMC 镜像里的 500 MiB vfat 切片（`loattach`+bind 到 `/dev/mmca*`），
  再加一层 LD_PRELOAD 的 Fsys 桩。但值得注意：**真 libInfraFsys + mcmn_drv 在 QEMU 里并不是完全死路**——
  p5 的 136 次卡切片读（69 KB）就是它经 QEMU 的 SD 数据通路读的（`ZZSDREAD p=0`），Round13 的 `Error 77` 已经不再是当前的拦路点。
- **(b) 桩可修，而且这一轮修掉两个真 bug**：
  ① `r14fshim_*.so` 用宿主 glibc（`GLIBC_2.34`）编的 → guest glibc 2.11.2 直接拒载（p1）；
  ② `Fsys_FindFirst` 真签名是 **3 参**（`pathbuf_inout, len=128, finddata`）且**路径要写回第 1 个参数缓冲区**（`SDFileManager::getFirmwarePath@0xda58`：成功后 `memcpy(out, this+12, 1037)`）——按 2 参写就会往地址 128 写 260 B ⇒ `page translation fault @0x00000080`（p2 的崩溃形态）；
  ③ `Fsys_Seek` 第三参**不是** SEEK_CUR/END（实测 `(h,20,20)`、`(h,32,32)`、`(h,212,212)`，且 checker 自己的日志说 `seek_point(20)`）⇒ 按绝对 `SEEK_SET` 处理后链子立刻走通（42→86）。
  桩现在无 libc（`-nostdlib -static -shared` + 裸 `svc`），`nm -D --undefined-only` 为空。
- **(c) 还没到验签**：读量（≤0.5 MB）+ shim 自己 `Fsys_Read=0 次` 双重证明；`FirmUp_Verify/Signature/Digest` 足迹 0 与此一致。
  拦路点已经**不是**总线/卡，而是**"版本相等不算升级"这道 UUD 门**（`Error 86`）。
  **要再来一轮**：p6（2.03 卡）就是为此发的车；若 p6 过了门，紧接着
  (i) 正样=无 `Signature Verification Error`，(ii) 负样=把翻位同样打在 2.03 的 FDAT 密文体里重跑，必须报错。
  若 p6 又出新码，仍然按"读量 + `R15FSHIM` 计数"判断走到哪一步。

## 补记（p6，2.03 卡，发车后 ~6 min 的进度）
- `SDUUDConditionChecker.cpp:53/54` = **`Old Version:2.0 … / New Version:2.3 Model:0x91030019 Region:0x0000`** ⇒ **UUD 门过了**（不再 `not meet UUD conditions`）。
- 之后它**第二次**走 UFU 链（DATV→PROV→UDID→`found FDAT`）= **取体/解密阶段开始**；
  `ZZSDREAD` 行数已涨到 **639,925 条 ≈ 327 MB**（对比之前每次 ~1,000 条）⇒ **整个 FDAT 正在被流式读进来**（这正是"走到摘要/解密"的读量判据）。
- 桩侧 `Open-size` 出现 2 次（两次打开同一文件）。
- p6 未跑完就被本轮收尾截断（`run_r15.sh p6 … 1800s`，日志 `~/qemu-a7c/r15_p6_boot1.*`）。
  **下一件事**：看 p6 尾部（`grep -av UD_COM_PIC r15_p6_boot1.ser | grep -aE "FIRMUP|Error|Update OK|MediaUpdate|reboot|R15-SDFILEINPUT-RC"`）
  + 统计 `grep -ac ZZSDWRITE r15_p6_boot1.out`（写表：如果开始出现 `rel=0x…` 落在 a1/a3/a10/a15/a23，就是**mode5 真的在写分区**了）。
