"""
创建阶段 1 测试数据：Excel 产品表 + 模拟 NAS 目录树。
"""
import os
import sys
from pathlib import Path

# ── 1. 测试 Excel ──
import openpyxl

TEST_DIR = Path("test_data")
TEST_DIR.mkdir(exist_ok=True)

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "产品列表"
ws.append(["69码", "产品名称", "产品描述"])
products = [
    ("693456781235", "2.5英寸移动硬盘盒 USB3.0", "支持SATA 3.0，免工具安装"),
    ("693456786789", "PCIE 4.0 x16 显卡延长线", "柔性排线，支持RTX 40系列"),
    ("693456781111", "Type-C 扩展坞 12合1", "HDMI 4K@60Hz，PD 100W充电"),
    ("693456782222", "DDR5 5600MHz 32GB内存", "笔记本内存，CL40，1.1V"),
    ("693456783333", "NVMe SSD 散热片", "纯铜散热鳍片，带导热硅胶垫"),
    ("693456784444", "Raspberry Pi 5 保护壳", "铝合金材质，被动散热"),
    ("693456789999", "万用表 数字 自动量程", "测量电压/电流/电阻/电容"),
    ("693456780000", "无图产品 测试用", "无对应图片文件夹的产品"),
]
for row in products:
    ws.append(list(row))
wb.save(TEST_DIR / "products.xlsx")
print(f"[OK] Excel: {TEST_DIR / 'products.xlsx'} ({len(products)} rows)")

# ── 2. 模拟 NAS 目录树 ──
NAS_DIR = TEST_DIR / "mock_nas"
# 清理旧数据
import shutil
if NAS_DIR.exists():
    shutil.rmtree(NAS_DIR)

folders = [
    # (文件夹名, 文件列表)
    ("2.5英寸移动硬盘盒 1235", ["front.jpg", "back.jpg", "inside.jpg", "package.webp"]),
    ("PCIE-4.0延长线_6789", ["cable.jpg", "connector.png"]),
    ("Type-C扩展坞 1111", ["hub.jpg", "ports.jpg", "box.png"]),
    ("DDR5笔记本内存 2222", ["ram.jpg"]),
    ("NVMe散热片 3333", ["heatsink.jpg", "install.jpg"]),
    ("Raspberry Pi 5 外壳 4444", ["case.jpg", "gpio.jpg"]),
    ("数字万用表 9999", ["meter.jpg"]),
    # 一个文件夹可能提取出多个4位码
    ("硬盘盒+扩展坞套装 1235 1111", ["combo.jpg"]),
    # 无码文件夹 — 不产生 folder_codes
    ("Misc_Parts_NoCode", ["random.jpg", "stuff.png"]),
    # 空文件夹 — 不产生 images
    ("EmptyFolder_5678", []),
]

for folder_name, files in folders:
    folder_path = NAS_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    for fname in files:
        fpath = folder_path / fname
        # 写入微小 "图片"（不是真实图片，但扩展名正确）
        fpath.write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(64))
        # 设置不同的修改时间
        os.utime(fpath, (1700000000 + hash(fname) % 100000, 1700000000 + hash(fname) % 100000))

print(f"[OK] NAS mock: {NAS_DIR}")
for folder_name, files in folders:
    fcount = len(files)
    print(f"       [{fcount}f] {folder_name}/")

print(f"\n总计: {sum(len(f) for _, f in folders)} 个图片文件, {len(folders)} 个文件夹")
print("\n测试数据就绪！运行: python test_phase1.py")
