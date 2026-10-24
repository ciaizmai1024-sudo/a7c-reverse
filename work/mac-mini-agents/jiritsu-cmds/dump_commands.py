#!/usr/bin/env python3
"""Dump the complete Jiritsu/SensTALK command surface to commands.tsv.

Sources (all offsets are file offsets in the shipped ELFs):
  disp   libsencore.so @0x1a218  1715 whitelist entries (stride 0x48)
  jir    libJiritsu.so @0x249c0  19 Jiritsu 0x1001 entries
  pfunc  libsencore.so hierarchy tables @0x61e30 (A), @0x61e78 (B), @0x61e98 (C)

Columns:
  table idx block code wire perm class qid name rw target risk note

RW/risk are derived from the command name and the block owner; they are
heuristics, not proof.  Anything the name does not resolve is marked "?".
The README explains which entries were verified against handler code.

Usage: python3 dump_commands.py [--tsv commands.tsv]
"""
import re
import sys

import sencore_tables as st

DISP_OFF = 0x1a218
DISP_LIMIT = 0x6b3          # TransactionStart scan bound
JIR_OFF = 0x249c0
JIR_LIMIT = 19

# block -> (owner / target description, risk floor for writes)
BLOCKS = {
    0x0101: ("应用层 testcmd/仿真", "中"),
    0x0102: ("显示/AF调整/测试", "中"),
    0x0103: ("FIFO/配置/日志", "中"),
    0x0201: ("应用基础设施 ILOG/事件", "中"),
    0x0202: ("应用基础设施 指示器", "低"),
    0x0203: ("应用基础设施 热靴", "中"),
    0x0204: ("应用基础设施 触摸", "中"),
    0x0205: ("应用基础设施 错误清除", "低"),
    0x0301: ("面板/EVF 调整", "中"),
    0x0302: ("面板/EVF 调整", "中"),
    0x0303: ("音频/麦克风诊断", "中"),
    0x0304: ("编解码诊断", "中"),
    0x0305: ("编解码诊断数据区", "中"),
    0x0306: ("AV 基板场景(SCN)", "中"),
    0x0307: ("AV 基板诊断", "中"),
    0x0308: ("投影/DPP", "中"),
    0x0309: ("AD/增益", "中"),
    0x030a: ("外部 EVF 检测", "中"),
    0x030b: ("外部 EVF OLED/按键", "中"),
    0x030c: ("SDI", "中"),
    0x030d: ("副 LCD/背光", "中"),
    0x030e: ("FURUD 类别存储", "高"),
    0x030f: ("热靴/鞋 ID/WiFi 端口", "高"),
    0x0310: ("TOKI 类别存储", "高"),
    0x0311: ("AV 板电源/信号开关", "中"),
    0x0312: ("回环/视频诊断", "中"),
    0x0313: ("FG/风扇", "中"),
    0x0314: ("温度", "只读"),
    0x0315: ("副 LCD/背光", "中"),
    0x0316: ("PS/眼感/ALS", "只读"),
    0x0317: ("转盘/TPU", "只读"),
    0x0318: ("CXS 板(固件/GPIO)", "高"),
    0x0319: ("PLL/时钟", "中"),
    0x031a: ("转盘/TPU", "只读"),
    0x031b: ("音频开关/告警", "中"),
    0x031c: ("时间复位", "低"),
    0x031d: ("MTG 复位", "中"),
    0x031e: ("TC/IO 开关", "中"),
    0x031f: ("手柄注册", "中"),
    0x0402: ("影像 LSI 调整", "中"),
    0x0404: ("影像 LSI 调整 G_/S_/A_/C_", "中"),
    0x0405: ("影像 LSI RAM", "中"),
    0x0408: ("影像 LSI 调整", "中"),
    0x040f: ("影像 LSI RAM", "中"),
    0x0415: ("影像 LSI RAM", "中"),
    0x0418: ("影像 LSI RAM", "中"),
    0x0420: ("相机场景(SCN)", "中"),
    0x0421: ("AF/传感器 store+RAM", "高"),
    0x0422: ("人脸信息清除", "低"),
    0x0423: ("竖拍手柄", "中"),
    0x0450: ("短片/省电设置", "低"),
    0x0460: ("AWB/IR 调整", "中"),
    0x0470: ("快门/帘幕调整", "中"),
    0x0480: ("DFE/CLC 调整", "中"),
    0x0490: ("镜头/曝光调整", "中"),
    0x04b0: ("微距灯/转盘", "中"),
    0x04c0: ("镜头/陀螺/灰尘调整", "中"),
    0x04d0: ("暗电流检查", "中"),
    0x04d1: ("暗电流/偏移调整", "中"),
    0x0501: ("视频/分量调整", "中"),
    0x0502: ("AVCE/MP2E 参数", "中"),
    0x0503: ("编解码诊断数据区", "中"),
    0x0601: ("ADJCTRL LSI 控制", "中"),
    0x0603: ("微控制器存储/PDT", "高"),
    0x0604: ("UD 更新/执行", "中"),
    0x0608: ("应用启动状态", "低"),
    0x0609: ("PDT/GPIO/TALLY", "高"),
    0x060a: ("ATN 信号", "中"),
    0x060b: ("NOR/日志", "高"),
    0x060c: ("选项卸载/唯一键", "高"),
    0x060d: ("时钟预设", "中"),
    0x060e: ("TALLY LED", "低"),
    0x0701: ("USB/充电/客户注册表", "高"),
    0x0702: ("JET 测速(场景)", "中"),
    0x0703: ("USB 日志读取/删除", "中"),
    0x0704: ("ADB 使能", "中"),
    0x0705: ("USB PD/充电", "高"),
    0x0801: ("GRM 取景器", "中"),
    0x0802: ("GRM 取景器", "中"),
    0x0901: ("ADC", "中"),
    0x0902: ("ADC", "中"),
    0x0903: ("GPIO", "低"),
    0x0b01: ("MPR 媒体/分区", "高"),
    0x0c01: ("HDMI RX/TX", "中"),
    0x0c02: ("USB 视频", "中"),
    0x0c03: ("HDMI 诊断", "中"),
    0x0c04: ("WLAN 固件/测试", "高"),
    0x0c05: ("诊断", "中"),
    0x0c06: ("指南针/加速度调整", "中"),
    0x0c07: ("相机诊断 API", "中"),
    0x0c08: ("相机诊断", "中"),
    0x0c09: ("I2C/HDCP", "高"),
    0x0c0a: ("NFC", "高"),
    0x0c0b: ("加速度/陀螺", "低"),
    0x0c0c: ("蓝牙固件/GPIO", "高"),
    0x0c0d: ("有线 LAN MAC", "高"),
    0x0c0e: ("选项卸载/唯一键", "高"),
    0x0c0f: ("寄存器读写", "中"),
    0x0d01: ("DD 电源", "高"),
    0x0d02: ("DD 通道电源", "高"),
    0x0d03: ("IB 电池信息", "中"),
    0x0d20: ("I2C 寄存器下载", "中"),
    0x0d21: ("相机/闪光灯状态", "中"),
    0x0e01: ("DMM 日志", "中"),
    0x0e02: ("DMM 日志", "中"),
    0x0f01: ("音频编解码调整", "中"),
    0x1001: ("Jiritsu 调试服务", "-"),
    0x1002: ("testcmd 引擎", "中"),
    0x1100: ("系统端口控制", "中"),
    0x2009: ("电源执行", "中"),
    0x2012: ("计时表", "中"),
    0x2015: ("版本读取", "只读"),
    0x2101: ("工厂复位/初始化", "高"),
    0x2301: ("音频/时码控制", "中"),
    0x2302: ("视频输入选择", "中"),
    0x2303: ("输出控制", "中"),
    0x2306: ("音频/彩条/取景器", "中"),
    0x2406: ("测试输出", "中"),
    0x2b01: ("录制/媒体", "高"),
    0x2b07: ("播放控制", "中"),
    0x3201: ("影像检查/备份", "中"),
    0x3205: ("影像自动调整", "中"),
    0x3301: ("信号输出", "中"),
    0x3401: ("音频输入/采样率", "中"),
    0x3501: ("FPGA/系统 I2C", "中"),
    0x3b01: ("NVM", "高"),
    0x4501: ("LCD/OLED/EEPROM", "高"),
    0x4b01: ("NVM", "高"),
    0x9001: ("库管理", "高"),
    0xffff: ("表终止符", "-"),
}
DUMMY_BLOCKS = (0x0402, 0x0409, 0x040a, 0x040b, 0x040c, 0x040d, 0x040e,
                0x0411, 0x0414, 0x0416, 0x041e, 0x04a0, 0x0602, 0x0605,
                0x0606, 0x0607)
for _b in DUMMY_BLOCKS:
    BLOCKS[_b] = ("保留/DUMMY", "?")

WRITE_RE = re.compile(
    r"(WRITE|SET|SAVE|DELETE|REMOVE|FORMAT|ERASE|CLEAR|RESET|POWER|ONOFF|"
    r"START|STOP|RUN|EXEC|LOAD|UPDATE|INSTALL|UNINSTALL|REBOOT|CTRL|CONTROL|"
    r"ADJ|CALC|MK_|MAKE|COPY|FLUSH|RECOVERY|PROGRAM|CONFIG|UPLOAD|DOWNLOAD|"
    r"CHG|SWITCH|TERM|SELECT|INIT|FINALIZE|COMPRESS|WRITE_|RMW)")
READ_RE = re.compile(
    r"(READ|GET|CHECK|CHK|STATUS|DUMP|INFO|VERSION|LOG|COUNT|HASH|MON|"
    r"DETECT|RESULT|LIST|ID|SENSE|MEASURE|POLL|SNAPSHOT|TALLY|READBACK)")
BRICK_RE = re.compile(
    r"(FORMAT|ERASE|UNINSTALL|CLEAR_DEVICE|FIRM|UPDATE_FW|REBOOT|"
    r"NOR_WRITE|PDT_WRITE|NVM_|EEPROM|UNIQUE_KEY|MK_PARTITION|MAKE_PARTITION|"
    r"PROGRAM_UCOMFW|LOAD_.*FIRMWARE|FACTORY_RESET|RECOVERY|FLASH_)")


def classify(name, block):
    if name.startswith("G_") or name.startswith("C_"):
        rw = "R"
    elif name.startswith("S_") or name.startswith("A_"):
        rw = "W"
    elif WRITE_RE.search(name):
        rw = "W"
    elif READ_RE.search(name):
        rw = "R"
    else:
        rw = "?"
    if block == 0xffff:
        return "?", "-", "表终止符"
    if rw == "R":
        return rw, "只读", ""
    base = BLOCKS.get(block, ("未知", "?"))[1]
    if base == "只读":
        base = "低"
    if block in (0x1001,):
        return rw, "?", ""
    if BRICK_RE.search(name):
        return rw, "高", "名称含固件/擦除/持久存储语义"
    if rw == "W":
        return rw, base if base in ("低", "中", "高") else "中", ""
    return rw, "?", "名称无法判定读写"


def class_of(code):
    scene = code & 0x1800
    if scene == 0x800:
        return "scenario"
    if scene == 0x1000:
        return "testcmd"
    if scene == 0:
        return "-"
    return "0xff"


def perm_of(code):
    if code & 0x8000:
        return "L3"
    if code & 0x4000:
        return "L2+"
    return "any"


# Curated overrides for blocks whose name heuristics misfire.
RISK_OVERRIDES = {
    (0x0b01, 0x10): "高", (0x0b01, 0x11): "高", (0x0b01, 0x21): "高",
    (0x0b01, 0x38): "高", (0x0b01, 0x44): "高", (0x0b01, 0x4f): "高",
    (0x0b01, 0x80): "高", (0x0b01, 0xe0): "高", (0x0b01, 0xe1): "高",
    (0x0b01, 0x30): "中", (0x0b01, 0x31): "中", (0x0b01, 0x33): "中",
    (0x0b01, 0x40): "中", (0x0b01, 0x41): "中", (0x0b01, 0x42): "中",
    (0x0b01, 0x43): "中", (0x0b01, 0x48): "中", (0x0b01, 0x49): "中",
    (0x0b01, 0x4a): "中", (0x0b01, 0x4b): "中", (0x0b01, 0x50): "中",
    (0x0b01, 0x51): "中", (0x0b01, 0x52): "中", (0x0b01, 0x63): "中",
    (0x0b01, 0x64): "中", (0x0b01, 0x65): "中", (0x0b01, 0x81): "中",
    (0x0b01, 0xe3): "中", (0x0b01, 0xe4): "中", (0x0b01, 0xe5): "中",
    (0x0b01, 0xe6): "中", (0x0b01, 0xe7): "中",
    (0x0702, 0x01): "中", (0x0702, 0x05): "中", (0x0702, 0x07): "中",
    (0x0601, 0xfe): "只读", (0x0601, 0xff): "中",
}
RW_OVERRIDES = {(0x0b01, 0x33): "W"}

JIR = [
    ("JIRITSU_MODE", 0x4001, "W", "模式切换(jmode)", "低", "切换 Manual/Normal 模式，不改文件"),
    ("JIRITSU_MOUNT", 0x4002, "W", "/dev/nflasha6 -> /tmp/jiritsu", "低", "挂载调试分区"),
    ("JIRITSU_FORMAT", 0x4003, "W", "/dev/nflasha6 (只经 /tmp/jiritsu 挂载点)", "中",
     "仅 sys_rm_tree /tmp/jiritsu 内容；不触碰 nflasha15 /usr；会删掉已投放脚本/备份"),
    ("JIRITSU_START", 0x4004, "X", "Jiritsu 脚本引擎(libJit.so + tmmc.jit)", "高",
     "启动脚本解释器；可执行主机投放的 libJit.so，等于任意代码执行"),
    ("JIRITSU_DEBUG", 0x4005, "W", "RTC", "低", "仅把时间设为 2017-07-04 21:42:26"),
    ("JIRITSU_FIRMUP", 0x4006, "W", "/tmp/jiritsu.bak.tar/.hash, ramdsk, /dev/nflasha6", "中",
     "更新包解包/备份/哈希；只作用于 nflasha6，未见写 nflasha15"),
    ("JIRITSU_SET_FILE", 0x4007, "W", "/tmp/jiritsu/<当前路径>", "中",
     "写调试分区文件，单文件 <=5MiB"),
    ("JIRITSU_GET_FILE", 0x4008, "R", "/tmp/jiritsu/<当前路径>", "只读", "读文件"),
    ("JIRITSU_FILE_DELETE", 0x4009, "W", "/tmp/jiritsu/<当前路径>", "中", "删文件"),
    ("JIRITSU_GET_FILELIST", 0x400a, "R", "目录列表", "只读", "列目录"),
    ("JIRITSU_GET_FILE_HASH", 0x400b, "R", "文件 MD5", "只读", "读文件哈希"),
    ("JIRITSU_COMPARE_MEDIA", 0x400c, "R", "/mnt/.compare 与主机数据比较", "低",
     "比较外部媒体内容，不写相机"),
    ("JIRITSU_GET_VERSION", 0x400d, "R", "/tmp/jiritsu/ver.txt", "只读", "读版本"),
    ("JIRITSU_FACTORY", 0x400e, "W", "工厂模式消息槽(全局)", "?", "数据 <=0xf0 字节，转发给内部信号量"),
    ("JIRITSU_SET_FILE_PATH", 0x400f, "W", "任意主机给定路径(不检查 '..')", "高",
     "只做 '\\'->'/' 与 \\n\\r, 拒绝；可路径逃逸到任意可写文件"),
    ("JIRITSU_SET_FILE2", 0x4010, "W/X", "任意路径, 写 libJit.so 时 dlopen 校验", "高",
     "可创建父目录；写 /tmp/jiritsu/libJit.so 后 dlopen+dlclose"),
    ("JIRITSU_GET_FILE2", 0x4011, "R", "任意主机给定路径", "中", "任意路径读"),
    ("JIRITSU_FILE_DELETE2", 0x4012, "W", "任意主机给定路径", "高", "任意路径删"),
    ("JIRITSU_TEST_UI_VIEW", 0x0013, "-", "-", "-", "桩函数，未实现"),
]

PFUNC = [
    ("A", 0x10, "ProductInfoFunc", "0x13834", "R", "产品信息", "只读"),
    ("A", 0x20, "FirmwareUpdateFunc", "0x13274", "W", "固件更新(8 字节桩)", "?"),
    ("A", 0x30, "MiconAccessFunc", "0x1356c", "-", "返回 NoAction 0x80", "只读"),
    ("A", 0x40, "AdjustControlFunc", "0x14bec", "W", "调整白名单总入口", "高"),
    ("A", 0xff00, "TestMode", "0x137dc", "W", "HostCommunicationCommand", "中"),
    ("A", 0xff01, "FileControl", "0x14d54", "W", "主机给定路径写文件", "高"),
    ("A", 0xff02, "SonarFunc", "0x1354c", "-", "空/handler", "只读"),
    ("A", 0xff03, "MemoryDump", "0x14af8", "R", "任意物理内存读(/dev/mem)", "只读"),
    ("B", 0x40, "AdjustControlFunc", "0x14bec", "W", "调整白名单总入口", "高"),
    ("B", 0x10, "ProductInfoFunc", "0x13834", "R", "产品信息", "只读"),
    ("B", 0x20, "FirmwareUpdateFunc", "0x13274", "W", "固件更新(桩)", "?"),
    ("C", 0x40, "AdjustControlFunc", "0x14bec", "W", "调整白名单总入口", "高"),
]


def main():
    out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--tsv" else "commands.tsv"
    rows = []
    d = open("out/bin/libsencore.so", "rb").read()
    ents = st.walk(d, DISP_OFF, "disp", DISP_LIMIT)
    for e in ents:
        name = e["name"]
        rw, risk, why = classify(name, e["block"])
        rw = RW_OVERRIDES.get((e["block"], e["code"] & 0xff), rw)
        risk = RISK_OVERRIDES.get((e["block"], e["code"] & 0xff), risk)
        cls = class_of(e["code"])
        if cls == "scenario":
            rw, risk = "X", "中"
            why = "场景类(code&0x1800==0x800)，会进 testcmd_run_scenario"
        target, _ = BLOCKS.get(e["block"], ("未知块", "?"))
        note = why
        if "参数" not in note:
            note = (note + "; " if note else "") + "参数=OSAL 负载(接收端 qid 定义)"
        if e["block"] == 0x0601:
            note = (note + "; " if note else "") + "参数/行为见 README 0x601 矩阵"
        elif e["block"] == 0x0603:
            note = (note + "; " if note else "") + "PDT=生产校准数据"
        elif e["block"] == 0x0b01:
            note = (note + "; " if note else "") + "媒体分区/格式化"
        rows.append(("disp", e["idx"], f"0x{e['block']:04x}", f"0x{e['code']:04x}",
                     f"0x{e['code'] & 0xff:02x}", perm_of(e["code"]), cls,
                     f"0x{e['qid']:08x}", name, rw, target, risk, note))

    jd = open("out/bin/libJiritsu.so", "rb").read()
    jents = st.walk(jd, JIR_OFF, "jir", JIR_LIMIT)
    for (name, code, rw, target, risk, note), e in zip(JIR, jents):
        assert e["code"] == code and e["name"] == name, (e, name, code)
        rows.append(("jir", e["idx"], "0x1001", f"0x{code:04x}",
                     f"0x{code & 0xff:02x}", perm_of(code), class_of(code),
                     f"0x{e['qid']:08x}", name, rw, target, risk, note))

    for lvl, code, name, addr, rw, target, risk in PFUNC:
        rows.append(("pfunc", lvl, "-", f"0x{code:04x}", f"0x{code & 0xff:02x}",
                     lvl, "-", "-", name, rw, target, risk, f"handler {addr}"))

    with open(out, "w") as f:
        f.write("table\tidx\tblock\tcode\twire_code\tperm\tclass\tqid\tname\trw\ttarget\trisk\tnote\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    print(f"wrote {out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
