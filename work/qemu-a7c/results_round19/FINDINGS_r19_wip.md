# Round 19 (r19) 中间结论(运行中，持续更新)

## 关键突破（主会话+本轮）：CBC-256 key 来源钉死
- Dec_Scramble/Init 的 provider = a1 /usr/lib/libupdatertalk.so（3.4KB，只管帧头 512B 的
  AES-128-ECB，KeyArray@vaddr 0x8830 硬编码 e3b0c442…/27ae41e4…，GOT-4=0x87f8，keyptr@+0x20，ctx@+0x28）。
- **真正的 AES-256-CBC 在 libInfraSKD.so（astra_data.c，SKData_Init/SKData_Exit，__GetCommonKeyData/__GetPublicKeyHash）**：
  SKData_Init = open("/dev/mem") → mmap(0x400 @ 0xFFFF5000) → mmap(0x20 @ 0xF340F000) → osal_reg_sync_msg_queue_cb。
  ⇒ **CBC-256 key 的输入 = 物理窗 0xF340F000 的 32 字节**（与 flash 无关，解释了整块 eMMC 搜不到 7e68a34d…）。
  我们 QEMU 里实测 setkey(256) key=7e68a34d… = QEMU 里 0xF340F000 这 32 字节的读回值。
- verifyKey 那 20B 很可能来自 0xFFFF5000 的 1KiB（待读回比对 SHA1(VerificationKey.pem)=184bbeff…）。

## r19 产物（全部 r19 tag，基线 a7c_emmc_pt4.img=8587674613a0… 未动）
- shim 源 r19src/r19fshim_full.c (md5 f719054d…)：= r18fshim_full + mincore 页探测 dump（r18 版直接读
  非指针参数 a1=0x3e014d 导致 translation fault，已修）+ /proc/self/maps dump + libupdatertalk KeyArray/GOT 槽
  dump（bt_dump，注：本轮忘了在 AES hook 里调用 bt_dump，r19bt2 跑里没有 R19BT 行——下轮补）+
  backup_sync_msg/Backup_read/osal_snd_sync_msg interpose + BURNMAP（/dev/nflashNN/<file> → /ramdsk/mntNN/<file> 真 vfat 后端）+ mincore 版。
  - r19fshim_r19bt2.so 7abf1c71…（FORCE0+FIXKEY）
  - r19fshim_r19burn2.so 74b382e2…（+BURNMAP）
- initrd：initrd_r19bt.img b5f2f877…（旧 shim，已弃）/ initrd_r19bt2.img 1faf5532… / initrd_r19burn2.img daa5d51a…
  （两 initrd 都在 sdfileinput.elf 行后注入 dd /dev/mem LOGB(0x03085000,0x478000)/PRTB(0x034FD000,0x8000) dump 到卡）
- 卡镜像：a7c_emmc_r19bt.img 4b38084a…（=r18fixf 卡副本）；a7c_emmc_r19burn.img 3fb047c2…（在 a1/a3/a5/a7/a15/a23
  分区 host 偏移处做了真 mkfs.fat；a1 也被 fat 化 = burn2 卡死的头号嫌疑，见下）。
- 跑：run_r19.sh（results_round19/）；日志 r19_bt_boot1.*（首跑，dump fault）、r19_bt2_boot1.*（修好）、r19_burn2_boot1.*（卡死）。

## P2 Backup 枚举（libbackup 层 interpose 首次成功）
- sdfileinput.elf 只导入 Backup_read；libbackup.so 全部走 backup_sync_msg（唯一咽喉，内部 plt 可被 LD_PRELOAD 抢）。
- 全程只有一条 Backup API 请求：**BackupID=0x4b0002**（Backup_read(id=0x004b0002, out=stack VA)，应答经
  osal uIPC 返回 ret=0，out 缓冲 d2 前 20B 全零 + 尾 d05f04；Backup_read 返回 24）。
  ⇒ verifyKey/20B 不走 libbackup（与 SKD 窗发现一致）。uIPC msg 队列在 maps 里：`04754000-04854000 rw 0x3dd00000 uipc`。
- ioctl interpose 依旧 0 命中（uIPC 走 libosal_uipc 直连 syscall，非可 interpose 的 ioctl）。

## P3 真 FAT/挂载
- burn2（BURNMAP+FAT 卡）：**没到 updater**，卡死在 boot 阶段的 R13-A23 持久性测试序列
  （写 a23→重启→读回 flood ZZSDREAD 0x50c39400+ 直到 timeout；serial 在第二次 boot 后无输出）。
  头号嫌疑：我们把 **a1 也 mkfs.fat 了**（a1 是 updater 文件分区，boot 链要读它）；次因：R13 a23 测试与
  FAT 化 a23 的交互。下轮 burn 卡：**a1 保留原内容不 fat 化**。
- bt2（假挂载+FIXKEY）：解密门过后照旧停在 Fsys_Open("/dev/nflasha23/INFO") 0x80000010 → **Error 43**（符合预期）。

## 待做
1. r19kbt 证据跑：bt 卡 + 无 FIXKEY + shell 里 dd /dev/mem 写 KEY_90045 到 0xF340F000 + dump 两窗到卡；
   verifySum 若自然过（无 :112 行）⇒ P1 完全闭环。
2. burn 卡去掉 a1 fat 化重跑（拿 ZZSDWRITE 写枚度）。
3. bt2 卡里的 r19logb.bin/r19prtb.bin（LOGB/PRTB）提取（dd host 侧 offset 0xbc00000 里 ls）。
4. AES hook 里补调 bt_dump（真机 setkey 调用点=libInfraSKD 的直接运行时证据）。
