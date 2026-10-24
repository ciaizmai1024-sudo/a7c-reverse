# 低风险注入点地图（按"改坏了能不能救"排序）

> 来源：MacBook 子代理 `setting-files` 全文报告见 `notes/setting-files-fullreport.md`；`modes` 报告见 `work/mac-mini-agents/modes/README.md`；下面**只列我自己在本地复核过证据的**。

## ★旗标梯与两条必须记住的更正（`modes` 轮，我逐条验过）

**旗标都在 `/setting/updater/` 下，看“文件存在与否”，内容无所谓（空文件即可）**。2.03 `UdtrMain.sh` 我对着行号看过（2.00 没有强制 PROD 那段）：

```
10:  test -f /root/IAMLDUDWRT            -> MODE_PROD      （恢复 ramroot 标记）
15:  test -f /setting/updater/mode  ||   -> Forced Prod Mode + touch /ramdsk/mode1   ← 2.03 上只放 mode5 无效！
18:  mode3 -> MINOR     21: mode2 -> SERVICE   24: mode6 -> VERSKIP   27: mode1 -> PROD   30: mode5 -> MSCRYPT(SD 卡链)
```

⇒ **优先级 `mode3 > mode2 > mode6 > mode1 > mode5`**；`mode4` 无读者（死键）；`mode2` 有读者无写者。
⇒ **`execute_ufp.sh:32-33`：`if [ -e /setting/updater/comp ]; then rm -rf /setting/updater/mode*`**（`comp` 是**空文件**，不是脚本）⇒ **旗标是一次性的**，这就是 QEMU 里 mode5 每轮要重注入的原因。
⇒ **`mode1` 会进产线链（`execute_prod.sh`），而产线链不做 comp 清理 ⇒ mode1 会残留**，以后每次进更新器都走产线链——放了要记得删。

**更正 1：不能说“刷固件不写 /setting”。** 更新器会 `mount /dev/nflasha2 /setting` 并增删旗标（`rm -rf mode*`、`touch MediaUpdateCompleteFlag`）、`libObj.so` 会 `mkdir /setting/mode` 写 `cmode`、`change_mode.sh` 写 `dmode/preload`、`up.sh` 写 `dat4`。⇒ **不格式化、不整块重刷，但目录项会变**；风险等级不变，但“a2 完全不动”这个说法作废。
**更正 2：影响正常开机的旗标不在 `updater/` 下**，而在 **`/setting/mode/`（`dmode`、`preload`，由 `bootin.elf` 每次正常启动读）和 `/setting/sen/`（`smode`）**；`/setting/updater/*` 只在进更新器时被读 ⇒ **改错最坏是更新会话失败/循环，不影响正常开机**（这块是安全游乐场）。

## /setting(a2 FAT12) 完整清单（我自己解的，之前那份解包不全）

```
UPDATER/{COMP(0 B), DAT4(2 B, 内容 00 02 = 当前版本 2.00)}
DmmConfig.bin 78,284 | .hasp 88 | .etools 4,096 | facedmy.bin 51,200 | facerec0..7.bin 各 57,888
Backup.bin 1,210,408 | Backup.bak 1,210,408 | psd.bin 4,427,776 | kemco.txt 1,905 | ulogio.bin 3,772
MODE/ (簇 440) | GPS/ (簇 4) | appfw_infra/
```

## 复核过的硬证据（主系统 initrd = a3 里的 `initrd.img`，**ext2**，2,186,240 B；`/sbin/init` 28,524 B）

```
/setting/mode/dmode        ← init 读的旗标
/setting/sen/smode        ← 又一个旗标（sen 目录）
/setting/env.txt          ← 环境变量文件（init 里有 parse_and_set_env / set_oreore_env / putenv）
/proc/udm/upm_bootmode    ← 启动模式经 procfs 读
LD_PRELOAD=/usr/tool/libkmcsup.so.2.0.0 | libsonyefence.so | libduma.so   ← init 自带三条调试 LD_PRELOAD
mounting /setting failed  +  /dev/nflasha2  +  /dev/nflasha3
```
另外那颗 initrd 里有 **`dosfsck`（64,774 B）** ⇒ a2(vfat) 的 FAT 坏了系统自己能修 ⇒ 动 /setting 的风险再降一档。

## 复核过的官方包侧（tar 成员，2.03）
```
0800_appli/setting/  ->  DmmConfig.bin, facedmy.bin, kemco.txt, appfw_infra/, ulogio.bin(2.03 新增)
0800_appli/tmp/      ->  config.spec, images/*(字体/图标, 2.03 换大字), kikilog.dat(2.03 新增), ...
```
⇒ **更新会重写 `/setting/ulogio.bin` 与 `/setting/kemco.txt`**：我的 TELN 补丁刷完 2.03 会被覆盖（要重打）；反过来，**改坏 kemco.txt 也能靠跑一次官方更新恢复**（多一条兜底）。

## vmlinux 侧（我复核）
`a3/extracted/vmlinux.bin`（4,117,632 B，裸 ARM32）里 **`kemco` magic 只出现 1 次（文件 `0x347bf4`）**；子代理给的解析补丁点 `0x391bf4`（VA `0x60499bf4`）附近确实是指针池/代码。结论：内核 cmdline 由 KEMCO 表补进 `setup_arch()`，**magic 必须为 `kemco`、上限 4096 B、无 CRC/版本字段**（⇒ 改错＝cmdline 空，可能开不了机，但官方更新可还原）。

## 排序（低风险 → 高风险）
1. **`/setting/mode/*`、`/setting/sen/smode`、`/setting/env.txt`**：默认不存在，建个文件就行；a2 更新不写、还有 dosfsck 与官方包兜底 ⇒ **R0–R1**。**最想知道的是它们各自触发什么**（已派下一轮去查 init 的分支）。
2. **`/setting/ulogio.bin` 的 TELN（`0x9c`）**：2.00 上是 root shell（见 `notes/ulogio-telnet-shell.md`）⇒ **R1**。
3. **`/setting/KEMCO.TXT`**：`console=`/`init=`/`root=`/`rdinit=`/`initrd=` 都进 cmdline；但 magic 错了可能不开机 ⇒ **R1–R2**（有官方包兜底）。
4. `DmmConfig.bin`/`facedmy.bin`：包内有正确字节 ⇒ R2。
5. `Backup.bin/.bak`、`psd.bin`、`.hasp`、`.etools`、`facerec0..7`：**设备独有，只能整盘 dump 才能复原** ⇒ R3。
6. `a3`/`a15`/`a1`：固件分区本体 ⇒ R0。
