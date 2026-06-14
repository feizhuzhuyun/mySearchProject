"""
准备阶段 1 完整测试数据：Excel 产品表 + NAS 目录树（模拟真实场景）。
运行：python prepare_test_data.py
输出：test_data/products.xlsx  +  test_data/nas_root/
"""
import os
import shutil
import openpyxl

BASE = "test_data"
NAS = os.path.join(BASE, "nas_root")
EXCEL = os.path.join(BASE, "products.xlsx")

# ── 清理 ──
if os.path.exists(NAS):
    shutil.rmtree(NAS)

# ═══════════════════════════════════════════════════════════════
# 1. 创建 Excel 产品表
# ═══════════════════════════════════════════════════════════════
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "产品列表"
ws.append(["69码", "产品名称", "产品描述"])
products = [
    ("693456781235", "2.5英寸移动硬盘盒 USB3.0",   "SATA 3.0，免工具安装，ABS材质"),
    ("693456786789", "PCIE 4.0 x16 显卡延长线",     "柔性排线 300mm，支持RTX 40系列"),
    ("693456781111", "Type-C 扩展坞 十二合一",       "HDMI 4K@60Hz, PD 100W, SD/TF卡槽"),
    ("693456782222", "DDR5 5600MHz 32GB 笔记本内存", "SO-DIMM，CL40，1.1V，海力士颗粒"),
    ("693456783333", "NVMe SSD 散热片 纯铜",         "双面散热，导热硅胶垫，2280规格"),
    ("693456784444", "树莓派5 铝合金保护壳",         "被动散热，GPIO开口，含导热贴"),
    ("693456789999", "数字万用表 自动量程",          "测量电压/电流/电阻/电容/频率"),
    ("693456785555", "USB4 40Gbps 数据线 1米",       "240W PD充电，8K视频传输"),
    ("693456787777", "RJ45 网络水晶头 100个装",      "CAT6屏蔽，50U镀金，穿孔式"),
    ("693456788888", "ESP32-S3 开发板",              "WiFi6/BLE5，16MB Flash，Type-C"),
    ("693456780000", "测试产品_无对应图片",           "此产品在NAS中没有匹配的图片文件夹"),
]
for row in products:
    ws.append(list(row))
wb.save(EXCEL)
print(f"[OK] Excel: {EXCEL}")
for p in products:
    print(f"     {p[0]} → {p[1]}")

# ═══════════════════════════════════════════════════════════════
# 2. 创建模拟 NAS 目录树
# ═══════════════════════════════════════════════════════════════

# 伪造图片：1×1 像素白色 PNG（最小合法 PNG，~68 字节）
FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"          # PNG signature
    b"\x00\x00\x00\rIHDR"         # IHDR chunk header
    b"\x00\x00\x00\x01"           # width=1
    b"\x00\x00\x00\x01"           # height=1
    b"\x08\x02"                   # bit depth=8, color type=2 (RGB)
    b"\x00\x00\x00"               # compression/filter/interlace
    b"\x12\x76\x93\x27"           # IHDR CRC
    b"\x00\x00\x00\x0eIDAT"       # IDAT chunk
    b"\x78\x9c\x62\x60\x60\x60\x00\x00\x00\x04\x00\x01"
    b"\x74\x94\x38\xb3"           # compressed pixel data + CRC
    b"\x00\x00\x00\x00IEND"       # IEND chunk
    b"\xae\x42\x60\x82"           # IEND CRC
)

folders = [
    # (文件夹名, [文件名列表])
    ("2.5寸硬盘盒_USB3.0_1235", [
        "正面图.jpg", "背面接口.jpg", "内部结构.png", "包装盒.webp", "尺寸图.bmp"
    ]),
    ("PCIE4.0延长线_300mm_6789", [
        "线缆整体.jpg", "接头特写.png", "包装.jpg"
    ]),
    ("TypeC扩展坞_12in1_1111", [
        "正面接口.jpg", "侧面接口.png", "包装盒.jpg", "说明书封底.jpg"
    ]),
    ("DDR5笔记本内存_32G_2222", [
        "内存正面.jpg", "标签特写.png", "上机图.jpg"
    ]),
    ("NVMe散热片_纯铜_2280_3333", [
        "散热片正面.jpg", "安装示意图.png", "包装.jpg"
    ]),
    ("树莓派5外壳_铝合金_4444", [
        "外壳正面.jpg", "GPIO开口.jpg", "安装效果.png"
    ]),
    ("数字万用表_自动量程_9999", [
        "万用表正面.jpg", "配件全家福.png", "屏幕点亮.jpg"
    ]),
    ("USB4数据线_40Gbps_1m_5555", [
        "数据线整体.jpg", "接口特写.png", "包装正面.jpg"
    ]),
    ("RJ45水晶头_CAT6_100个_7777", [
        "水晶头特写.jpg", "包装袋.png"
    ]),
    ("ESP32-S3开发板_TypeC_8888", [
        "开发板正面.jpg", "IO引脚图.png", "上电测试.jpg"
    ]),
    # ── 多码文件夹：一个文件夹包含多个4位码 ──
    ("硬盘盒+扩展坞_套装_1235_1111", [
        "套装组合.jpg", "对比图.png"
    ]),
    # ── 无码文件夹：名称不含4位数字 ──
    ("Misc_PCBA_NoCode", [
        "主板.jpg", "元件特写.png"
    ]),
    # ── 空文件夹：没有图片 → 不产生 images 记录 ──
    # (不创建，或创建空文件夹)
]

for folder_name, files in folders:
    path = os.path.join(NAS, folder_name)
    os.makedirs(path, exist_ok=True)
    for fname in files:
        fpath = os.path.join(path, fname)
        with open(fpath, "wb") as f:
            f.write(FAKE_PNG)
        # 设置不同的修改时间（用于增量扫描测试）
        mtime = 1700000000 + hash(fname) % 500000
        os.utime(fpath, (mtime, mtime))

# 创建空文件夹
os.makedirs(os.path.join(NAS, "EmptyFolder_5678"), exist_ok=True)

print(f"\n[OK] NAS: {NAS}/")
total_files = 0
for folder_name, files in folders:
    fc = len(files)
    total_files += fc
    print(f"     [{fc:1d}f] {folder_name}/")
print(f"     [0f] EmptyFolder_5678/ (空)")
print(f"\n总计: {total_files} 张图片, {len(folders)+1} 个文件夹")
print(f"\n请将 config.json 中的 nas_root_path 设置为:")
print(f"    {os.path.abspath(NAS)}")
