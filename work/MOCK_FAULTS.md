# MOCK_FAULTS — 阶段 1：mock 故障矩阵（执行边界落在代码里的验收）

跑法：`bash tools/tests/mock_faults.sh`（全离线，`--mock`，mock 根 `work/mock-faults`，不污染 `work/mock`，不碰 USB/相机）。
判定标准：每种故障都必须【真的停止】——退出码非 0 / 写序列中断，**不是只打印警告**。
最近一次运行：PASS=19 FAIL=0（含健康基线 + wrapw happy-path 另测 OK）。

| # | 故障 | 注入方式（mock） | 期望 | 结果 |
|---|------|------------------|------|------|
| 0 | 健康基线 | 正常 mock | `preflight` → `PREFLIGHT PASS`, rc=0 | PASS |
| 1 | 写没有 `--allow-write` | `fput/put/fdel/del` 各一次 | 全部拒绝 rc=1，输出含「默认 RO」 | PASS ×4 |
| 2 | 白名单外路径 | `--allow-write --level L2.5 fput /usr/bin/up.sh`；`fput /setting/updater/comp`；未知级别 L9 | 拒绝 rc=1（comp 不在 L2.5 名单里，写它属于更高阶梯） | PASS ×3 |
| 3 | 危险 opcode | `jir 0x4003`（FORMAT）/ `jir 0x4004`（START）无旗标 | 拒绝 rc=1；`jir 0x4006 --i-know-what-im-doing` 可发且打印 `⚠⚠` 警告 | PASS ×3 |
| 4 | 设备身份不符 | `$M/device_desc.tsv` 改 `bcdDevice=0x0203`；另一例改 PID=`0d2a`(MTP) | `preflight` rc=1，命中 [1] | PASS ×2 |
| 5 | 版本不符 | `$M/fs/setting_updater_dat4` = `00 03`（2.03） | `preflight` rc=1，命中 [2] | PASS |
| 6 | updater mode 旗标残留 | 预置 `$M/fs/setting_updater_mode` | `preflight` rc=1，命中 [5] 并提示先跑 `us_remove_modes.sh` | PASS |
| 7 | 读不完整 | `$M/dev/nflasha7` 只给 4096 B（partinf 期望 8,388,608） | `dump` rc=1：「dump 失败：…partinf.conf 期望」 | PASS |
| 8 | 部分写/读回少字节 | `MOCK_TRUNC_READ=7`（FileControl 读少返回 7 B）跑 `tools/wrapw.sh` | 写后 `fget` 校验发现字节数/sha 不符 → rc=1「读回字节数/内容与源不符」 | PASS |
| 9 | 旧 zzprobe 残留 | 预置 `$M/fs/tmp_zzprobe`（内容非本次探针） | `wrapw.sh` 写前 `fget` 定状态 → rc=2「已存在…不静默覆盖」 | PASS |
| 10 | 工具被改 | 临时把 `work/TOOL_HASH` 换成 deadbeef… | `preflight` rc=1，命中 [3]「工具 sha 不符」 | PASS |

## 设计要点 / 语义
- 门禁在 `tools/jiritsu_send.py`：`gate_write()` + 写死表 `WRITE_WHITELIST`（L2.5=三个 zzprobe + `/usr/lib/zzprobe` 边界探针；L4-jit=libJit.so）。默认 RO；写=`--allow-write` + `--level` + 路径在名单内，三者缺一不可。
- 边界探针 `/usr/lib/zzprobe` **只允许失败**：真写成功 => `fput` 打警告并 `exit 4`（mock 下必然触发，因为 mock fs 无保护区）；`wrapw.sh` 接住 rc=4，尝试 `fdel` 清理残留后仍 exit 4 停序列。
- 写不自动重试：`jir()` 对 code 16/18/0x40xx 全部 `retries=0`；`raw` 也 `retries=0`；FileControl 写不经重试环。**远端 `wrap2.sh` 的 5 连重试对写不可用**，本机替代品是 `tools/wrapw.sh`（单发 + 写前/写后 `fget`）。
- mock 故障注入开关：`device_desc.tsv`（设备身份）、`fs/*` 覆写（dat4/mode/comp/残留 zzprobe）、`$M/dev/<name>`（分区镜像截短，优先于固件包回退）、env `MOCK_TRUNC_READ=N`（读回截短）。

## 已知遗留（跑真机前要注意，不在本轮修）
1. **pmca 仍有 4-NUL padding bug**：`refs/Sony-PMCA-RE/pmca/usb/sony.py:1001` 的 `_sendFileControlPacket` 还是 `b'\0'*(4-len%4)`——文件名长度已是 4 倍数时多补 4 个 NUL。工具里只有 MockCam/frames 修过（`(-len)%4`）；**真机路径走 pmca**，所以名字为 4 倍数长度的路径（如 `/tmp/zzprobe`=12B、`/usr/lib/zzprobe`=16B、`/version.txt`=12B）在真机上可能撞 error 130。接相机第一步应先用 `fc=2:/tmp/zzprobe` 读探针验证，必要时把工具内 FileControl 改成自带 framing（一行改动，位置已标）。
2. mock 下 `/dev/nflasha7`、`/dev/nflasha15` 回退用固件包内**短镜像**（4,992,000 / 239,982,592 B）——`dump` 在 mock 里对这两个必然判长度失败，这是特性不是 bug（见 `work/BACKUP_MANIFEST.tsv` 的 LENGTH-MISMATCH 标记）。
3. `preflight --mock` 用 `work/mock` 默认根时，`fs/tmp_zzprobe` 有历史残留（旧实验留的）——它不影响 preflight 六项，但真跑探针前先 `fdel` 或换 mock 根。
4. `l1` 子命令对单个分区 dump 失败仍是「记下继续」（收集型阶梯不中断）；单跑 `dump` 才会非 0 退出。写序列的中断语义由 `wrapw.sh` 保证。
