# 低风险注入点地图（按"改坏了能不能救"排序）

> 来源：MacBook 子代理 `setting-files` 全文报告见 `notes/setting-files-fullreport.md`；下面**只列我自己在本地复核过证据的**（复核命令都是在这台机器上跑的）。

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
