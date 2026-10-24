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

## 追加（23:20-23:45）
- kbt 首试（shell dd /dev/mem 写窗）RC=1 全失败：PA 0xF340F000 > 2^31，initrd busybox dd 无 LFS。
  ⇒ 改在 shim 里 mmap2(/dev/mem, PA>>12) 直写（r19add: skd_window_patch()，Dec_ScrambleInit 钩内、先于 256-bit setkey），同时 dump 0xFFFF5000 那 1KiB 到串口。
- kbt（无 FIXKEY、key 窗未写）：verifySum 自然失败 → UdrAPI,196610,DecryptorModule.cpp:112,"6157:664" → Error 42（r18 现象复现，链上无其它门被挪动）。
- LOGB(0x03085000)/PRTB(0x034FD000) 已 dd 出（r19logb.bin 4.68MB md5 89b6dc1e…，r19prtb.bin 32KB md5 bb7df04e…）：内容 = RBUF/SUBS 二进制记录，非明文；且内核早期 "Logger@Error can't get alog.addr & alog.size! Alloc memory by logger itself!" ⇒ ulogio 未用保留窗（自分配），LOGB 无 updater 明文（PRTB 空）。下轮先修 Logger alog.addr/size 参数。
- 新产物：r19fshim_r19k2.so / r19fshim_r19kb.so（源 r19src/r19fshim_full.c）；initrd_r19k2.img ac9b99fc… / initrd_r19kb.img a547ff92…；卡 a7c_emmc_r19kbt.img 4cad789b… / a7c_emmc_r19burnk.img 5fe6d0f2…（burn 卡 + a1 段从 r18fixf 原样恢复 = burn2 卡死头号修复）。
- 在跑：r19_k2（bt卡+mmap2写KEY,无FIXKEY,预期 verifySum 自然过 → 到 Error 43）；r19_kb（burn卡+BURNMAP shim：真 FAT + 写 KEY → 目标 burn/ZZSDWRITE）。

## 追加（00:00-00:30）：key 来源与 P3 门推进
- **0xF340F000 在 QEMU 里是 hole**：shim mmap2 读=全零、写不回读（POST 仍全零）。而 k2/kb（写窗尝试后）
  setkey-256 key 仍 = 7e68a34d…（跨所有 run 确定性不变）⇒ **在 QEMU 里这把 key 不来自那个物理窗**；
  SKData 的 key 取给路径另有来源（uIPC/mcmn 队列应答或 SKD 内部静态缓冲），真机上由 DSP 侧（OTP/eFUSE 域）
  提供 —— 与"两把 key 都不在 flash/Backup"完全一致。判据到此（调用点+来源层），真机仍需 RPMB/DSP 侧证据。
- libInfraSKD.so（a1 /usr/lib，已加载 @0x04009000）导入 **EVP_aes_256_cbc/EVP_CipherInit/EVP_CipherUpdate/
  EVP_CIPHER_CTX_new** ⇒ 256-bit 解密走 EVP（这就是 AES_set_decrypt_key(bits=256) 被 libcrypto 内部调起、
  而 a1 各 ELF 导入表里看不到 AES_* 的原因）。
- k3（bt_dump 生效）：`R19BT SETDEC128 ra0=0001121f keyp=04361830` —— ra0 在 **sdfileinput.elf** text（其
  verifySum 副本 @0x11274 同一函数簇，Dec_ScrambleInit 尾调用链的原始调用方）；SETDEC256 的 bt_dump 被
  n_setkey<=3 上限卡掉（该 run 里 256 是第 4 次 setkey），下轮把上限放宽即可拿到 256 的 ra0/keyp。
  注意 mincore 页探测在本 guest 内核过严（栈页也报未映射 → dump 变 ??），下轮换"读前先查 /proc/self/maps 缓存"。
- kb2（burn 卡 + FIXKEY + BURNMAP）：**过了 r18 的 FsysWrapper INFO 门**（0x30022/43 不再出现），
  进到 `Plugin.cpp:54 "us_darwin_firm.sh"` → `ud_darwin_firmup.elf`（Darwin CRC spam）返回 255 →
  getledval 0x63 → **Error 63**（新终点，比 r18 远一层）。
  另：R19-MOUNTa23-RC=255 —— a23 的 mkfs.fat 被 boot 期 R13-A23 写测试（64KB 覆写 a23）破坏；
  a1/a3/a5/a7/a15 全部挂载 RC=0（真 FAT 挂载成立）。
- kb3（在跑，00:25 起）：burn 卡 + FIXKEY+BURNMAP + **us_darwin_firm.sh 打点 exit 0** + **boot 脚本里
  先 mkdosfs /dev/nflasha23 再 mount** ⇒ 目标：进 NewFirmwareFile/burn，抓 Fsys_Write/ZZSDWRITE 写枚度。
- 写枚度（boot 级基线）：k2/k3/kb run ZZSDWRITE≈9250（R13 a23 测试+重启+卡元数据），bt2=27913，r18 系=0-11。

## 最终产物清单（r19；基线 8587674613a0ffd86beea010e74fd44c10e74fd47c→原文为 8587674613a0ffd86beea010e74fd47c 未动，复核 OK）
- shim 源 r19src/r19fshim_full.c（最终 md5 见 MANIFEST_r19）；.so：r19bt2/burn2/k2/kb/k3/kb2（r19src/）
- initrd：initrd_r19bt(弃)/r19bt2/r19burn2/r19kbt(弃)/r19k2/r19k3/r19kb/r19kb2/r19kb3（results_round19/）
- 卡：a7c_emmc_r19bt / r19burn / r19kbt / r19burnk(a1 段从 r18fixf 恢复) / r19k3 / r19kb2 / r19kb3
- guest 文件：results_round19/guestfiles/{r19logb.bin 89b6dc1e..., r19prtb.bin bb7df04e...}（RBUF 记录非明文；
  根因：内核 "Logger@Error can't get alog.addr&size ⇒ 自分配缓冲"，下轮先修 alog 参数）
- 串口：r19_{bt,bt2,burn2,kbt,k2,kb,k3,kb2,kb3}_boot1.{ser,out}；跑脚本 results_round19/run_r19.sh

## 追加（00:00-00:30）：key 来源与 P3 门推进
- 0xF340F000 在 QEMU 里是 hole：shim mmap2 读=全零、写不回读（POST 仍全零）。而写窗尝试后 setkey-256 key
  仍 = 7e68a34d…（跨所有 run 确定性地不变）⇒ 在 QEMU 里这把 key 不来自那个物理窗；SKData 的取 key 路径
  另有来源（uIPC/mcmn 队列应答或 SKD 内部缓冲），真机上由 DSP 侧（OTP/eFUSE 域）提供 —— 与"两把 key
  都不在 flash/Backup"一致。判据（调用点+来源层）到此；真机值仍需 DSP/RPMB 侧证据。
- libInfraSKD.so（a1 /usr/lib，已加载 @0x04009000）导入 EVP_aes_256_cbc/EVP_CipherInit/EVP_CipherUpdate/
  EVP_CIPHER_CTX_new ⇒ 256-bit 解密走 EVP（这解释了 AES_set_decrypt_key(bits=256) 由 libcrypto 内部调起、
  a1 导入表看不到 AES_* 的原因）。
- k3（bt_dump 生效）：R19BT SETDEC128 ra0=0001121f keyp=04361830 —— ra0 在 sdfileinput.elf text（其
  verifySum 副本 @0x11274 同一函数簇；= Dec_ScrambleInit 尾调用链的原始调用方）。SETDEC256 的 bt_dump 被
  n_setkey<=3 上限卡掉（该 run 里 256 是第 4 次 setkey），下轮放宽即可。mincore 探测在本 guest 过严
  （栈页也 ??），下轮换"读前查 /proc/self/maps 缓存范围"。
- kb2（burn 卡 + FIXKEY + BURNMAP）：过了 r18 的 FsysWrapper INFO 门（0x30022/Error 43 消失），进到
  Plugin.cpp:54 us_darwin_firm.sh → ud_darwin_firmup.elf（Darwin CRC spam）返回 255 → getledval 0x63 →
  **Error 63**（新终点，比 r18 远一层）。R19-MOUNTa23-RC=255：a23 的 FAT 被 boot 期 R13-A23 写测试破坏；
  a1/a3/a5/a7/a15 挂载 RC=0（真 FAT 挂载成立）。
- kb3（在跑，00:25 起）：burn 卡 + FIXKEY+BURNMAP + us_darwin_firm.sh 打点 exit 0 + boot 脚本先
  mkdosfs /dev/nflasha23 再 mount ⇒ 目标：进 NewFirmwareFile/burn，抓 Fsys_Write/ZZSDWRITE 写枚度。
- 写枚度基线：k2/k3/kb ZZSDWRITE≈9250（R13 a23 测试+重启+卡元数据），bt2=27913，r18 系=0-11。

## 产物清单（r19；基线 a7c_emmc_pt4.img=8587674613a0ffd86beea010e74fd47c 复核未动）
- shim 源 r19src/r19fshim_full.c；.so：r19bt2/burn2/k2/kb/k3/kb2/kb3 同目录
- initrd（results_round19/）：r19bt(弃)/r19bt2/r19burn2/r19kbt/r19k2/r19k3/r19kb/r19kb2/r19kb3
- 卡：a7c_emmc_r19bt/r19burn/r19kbt/r19burnk(a1 段从 r18fixf 恢复)/r19k3/r19kb2/r19kb3
- guest 文件：guestfiles/{r19logb.bin md5 89b6dc1e…, r19prtb.bin md5 bb7df04e…}（RBUF 记录非明文；
  根因：内核 Logger@Error cant get alog.addr&size ⇒ 自分配缓冲；下轮先修 alog 参数再取 LOGB）
- 串口：r19_{bt,bt2,burn2,kbt,k2,kb,k3,kb2,kb3}_boot1.{ser,out}；脚本 results_round19/run_r19.sh

## kb3（mkdosfs a23 修好 + us_darwin_firm 打点）——burn 首证
- R19-MOUNT a1/a3/a5/a7/a15/a23 全 RC=0（a23 先 mkdosfs 再挂，真 FAT 成立）。
- 链条：Format(a23) 过 → stub plugin 过 → body 读完 BODYDATA 帧流（Read-eof 535MB）→ 二次 Fsys_Init +
  Mount(a23, 走 Mount-burn-dir /ramdsk/mnt23) → **开始写**。
- kb3 ZZSDWRITE 聚合（rel=USER 区偏移，512B 粒度）：
  0x50800000 a23: 20KB（FAT 元数据+INFO）；0x800000/0x810000/0x1004a00 a2: ~1.2MB+元数据；
  0x2D40C400/0x2D410600 a13: 非易失存储；0x5800000 a5: 512B（挂载脏位）；0xb82e000 卡: 4KB；
  **0x10000..0x7FFFFF a1: 8,323,072B = 恰好 2.03 tar 成员 0400_updater/dev/nflasha1 (0x7F0000) 全量写入** =
  第一条完整 burn 分区写（先写 a1）。
- kb3b（00:47 起，timeout 1500s，同卡同 initrd）：等 a15/a3/a5/a7 大写入 + reboot 读回。

## kb3（mkdosfs a23 修好 + us_darwin_firm 打点）——burn 首证
- R19-MOUNT a1/a3/a5/a7/a15/a23 全 RC=0（a23 先 mkdosfs 再挂，真 FAT 成立）。
- 链条：Format(a23) 过 → stub plugin 过 → body 读完 BODYDATA 帧流（Read-eof 535MB）→ 二次 Fsys_Init +
  Mount(a23, 走 Mount-burn-dir /ramdsk/mnt23) → 开始写。
- kb3 ZZSDWRITE 聚合（rel=USER 区偏移，512B 粒度）：
  0x50800000 a23: 20KB（FAT 元数据+INFO）；0x800000/0x810000/0x1004a00 a2: ~1.2MB+元数据；
  0x2D40C400/0x2D410600 a13: 非易失存储；0x5800000 a5: 512B（挂载脏位）；0xb82e000 卡: 4KB；
  0x10000..0x7FFFFF a1: 8,323,072B = 恰好 2.03 tar 成员 0400_updater/dev/nflasha1 (0x7F0000) 全量写入
  = 第一条完整 burn 分区写（先写 a1）。
- kb3b（00:47 起，timeout 1500s，同卡同 initrd）：等 a15/a3/a5/a7 大写入 + reboot 读回。
- kb3b（复用 kb3 卡）无效：kb3 已把 a1 全量 burn（8MB 覆写 a1 的 vfat/updater 文件），下次 boot 的
  updater 环境被毁 → boot 早停（cmdline 退回默认、ser 18KB、只有 r13 64KB 写）。教训：**burn 跑每轮必须换新卡**
  （burnk 配方：r18fixf 卡 + mkfs.fat on a3/a5/a7/a15/a23 + a1 段保留 r18fixf —— 本轮 a1 burn 会毁掉 boot-下一轮）。
- P4 reboot 读回：本轮未做（burn 未完成，a1 已被毁即副作用证据）。
