# R16-A: p6 榨干（boot1+boot2 均已结束）

## p6 boot1（a7c_emmc_r15v203.img, initrd_r15e, map g）
- UUD 门过（Old 2.0 < New 2.3, Model 0x91030019）→ 第二次走链 `found FDAT` →
  `SDDecryptorModule.cpp:64 "Waiting for Firmware Copy Completion"`。
- 然后 guest 内核 oops（t=50.07s）：`Unable to handle kernel paging request at virtual address b0800000`,
  `*pgd=1e135811, *pte=00000000`, PC=memcpy+0x48, 进程 loop0 (pid 112)，栈=
  loop_thread→splice_direct_to_actor→lo_direct_splice_actor→splice_from_pipe_feed→lo_splice_actor→transfer_none。
  QEMU 进 exception monitor，卡死（被手工 kill）。
- boot2 复跑 = **完全相同**：同点 `found FDAT`→copy→t=48.9s 同一地址 b0800000 同一 memcpy Oops ⇒ **确定性**。
- ZZSDREAD 总计 639,925 条（boot1）。按宿主地址解析：BODYDATA.DAT 的 UFU 魔数 DATV 在镜像宿主偏移 0xbc3400c
  ⇒ 文件起点对应宿主 0xbc34000。落在文件区的读 = 638,648 条 ×512B，**恰好覆盖文件 offset 0 .. 0x137D7000 (326,987,776B, 全文件 363,197,944B 的 90.0%)，单段无空洞**；
  文件尾（含签名区最后 0x100B、payload 尾区）**从未被读** ⇒ p6 里验签（若消息=尾256B之前的整段）至多做到 90%，
  **没有单独读尾部 256B 的读**，没有任何 Signature/Verify 类日志，没有任何固件分区写。
- 本轮 eMMC 写只有 3 条：ZZSDWRITE rel=0x810a00 / 0x800a00 / 0x800200（a2 旗标区），无固件分区写。

## 崩溃根因（离线可证，不用改 QEMU/内核）
- 内核编译期 CONFIG_CXD900X0_SIZE_DDR0=0x40000000、SIZE_DDR1=0x10000000(256MB)、PAGE_OFFSET=0x60000000。
  boot 日志：`vmalloc : 0xb0800000`、`Memory: 1024MB 1016MB = 2040MB total`（map g 给了 1016MB DDR1）。
- 线性窗只映射到 vmalloc 底 **0xB0800000**（= VA_DDR1 0xA0000000 + 0x10800000），即 DDR1 前 264MB 有 pte、其后 pte=0。
- 固件拷贝把 order-0 页一路吃到 DDR1 的 PA 0x90800000（自定义 __va: VA=PA-0x20000000 → VA 0xB0800000）→ 无 pte → memcpy oops。
  拷贝边界 0x137D7000 正好 = 0xB0800000-0x9D029000（消费缓冲顶到窗顶），分毫不差。
- 触发条件 = 内存吃紧：cmdline 里 `memrsv=0x20000000@0x20000000:uc` 把 DDR0 的 512MB 标成 device（不进 buddy），
  加上其它 reserved，拷贝开始前"映射内空闲"只剩 ~330MB < 363MB。
- **修法（不改码）**：新 cmdline 文件删掉 `memrsv=0x20000000@0x20000000:uc` ⇒ 拷前映射内可分配提高到 ~1.2GB（DDR0 940M + DDR1 映射窗 264M），
  拷贝 363MB 不会越进无映射的 DDR1 深水区。r16 各跑用 parts/kemco_a1_r16.txt。
