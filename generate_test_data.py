"""
生成模拟测试数据：假 NAS 目录 + 产品图片 + CSV 导入 + 扫描索引。

用法：
    python generate_test_data.py          # 生成数据并扫描
    python generate_test_data.py --clean  # 清空后重新生成
"""
import os, sys, shutil, argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 项目根
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_NAS = os.path.join(BASE_DIR, "test_nas")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ── 测试产品定义 ──────────────────────────────────────────────
# (full_code, name, description)
TEST_PRODUCTS = [
    # 转接卡 — 蜻蜓系列（同组多 SKU）
    ("6933910412233", "PCIe4.0转M.2转接卡 蜻蜓x1（不挡显卡）型号：P717",
     "PCIE adapter"),
    ("6933910412240", "PCIe4.0转M.2转接卡 蜻蜓X4（不挡显卡）型号：P707",
     "PCIE adapter"),
    ("6933910412260", "PCIe4.0转M.2转接卡 蜻蜓Pro 22110版 型号：P760",
     "PCIE adapter"),
    # 转接卡 — B526
    ("6933910412257", "2230 NVME转SD Express转接卡 型号：B526",
     "PCIE adapter"),
    # 转接卡 — RZ系列
    ("6933910423925", "M.2 NVMe转PCIE 4.0 X1 转接卡 型号：RZ401",
     "PCIE adapter"),
    ("6933910423932", "M.2 NVMe转PCIE 4.0 X4 转接卡 型号：RZ404",
     "PCIE adapter"),
    # 延长线（自定义 SKU）
    ("PG40X16LL1890BK50", "工程级散线 PCIE4.0 X16显卡延长线(1890) 左进左出 50CM 黑色",
     "PCIE Riser Cable"),
    ("PG40X16LL1890WT50", "工程级散线 PCIE4.0 X16显卡延长线(1890) 左进左出 50CM 白色",
     "PCIE Riser Cable"),
    # 延长线（69码）
    ("6933910422966", "PCIE 5.0 X16显卡延长线(180度 1890) 25CM 白色",
     "PCIE Riser Cable"),
    # 硬盘盒
    ("6933910412363", "JEYI 3.5寸5G双盘硬RAID阵列硬盘盒 型号：Giboat3502",
     "HDD Enclosure"),
    # 水晶头护套（自定义 SKU 多颜色变体）
    ("HT65PCBU001", "6.5MM PC水晶头护套 蓝色 1个装 型号：HT65PCBU001",
     "RJ45 Boot"),
    ("HT65PCBK001", "6.5MM PC水晶头护套 黑色 1个装 型号：HT65PCBK001",
     "RJ45 Boot"),
    ("HT65PCRD001", "6.5MM PC水晶头护套 红色 1个装 型号：HT65PCRD001",
     "RJ45 Boot"),
    # 水晶头
    ("C6S1TKBU001", "六类非屏蔽通孔蓝色水晶头 一排1.08mm 单个装",
     "RJ45 Connector"),
    # 散热
    ("6933910406300", "佳翼 散热片海鲨二代 红色",
     "Heatsink"),
    # 支架
    ("6933910423529", "适合两/三卡位 显卡竖装加长支架 白色",
     "GPU Bracket"),
]

# ── 模拟 NAS 目录结构 ──────────────────────────────────────────
# folder_path → [子文件夹列表（相对于 folder_path）]
FOLDER_STRUCTURE = {
    "2.转接卡/蜻蜓系列 2233 2240 2260": [
        "中文", "英语", "西班牙语", "俄语", "渲染图", "实拍图",
    ],
    "2.转接卡/B526 2257": [
        "中文", "英语", "渲染图", "实拍图",
    ],
    "2.转接卡/RZ系列 3925 3932": [
        "中文", "英语", "韩语", "渲染图", "实拍图",
    ],
    "13.PCIE延长线/延长线1890系列 0566": [
        "中文", "英语", "亚马逊", "俄语", "印尼语", "实拍图", "渲染图", "西班牙语", "韩语",
    ],
    "13.PCIE延长线/PCIE5.0延长线 2966": [
        "中文", "英语", "实拍图", "渲染图",
    ],
    "5.硬盘盒/Giboat3502 2363": [
        "中文", "英语", "实拍图", "渲染图", "亚马逊",
    ],
    "10.水晶头/水晶头护套多色": [
        "中文", "英语", "实拍图",
    ],
    "10.水晶头/通孔水晶头": [
        "中文", "英语", "实拍图",
    ],
    "6.散热/海鲨二代 6300": [
        "中文", "英语", "实拍图", "渲染图",
    ],
    "9.支架/显卡竖装支架 3529": [
        "中文", "英语", "实拍图",
    ],
}

# ── 每类产品的配色 ─────────────────────────────────────────────
COLORS = {
    "转接卡":   ("#1A5276", "#85C1E9"),  # 深蓝底 + 浅蓝文字
    "延长线":   ("#1E5128", "#A9DFBF"),  # 深绿底 + 浅绿文字
    "硬盘盒":   ("#7D3C21", "#F0B27A"),  # 深橙底 + 浅橙文字
    "水晶头":   ("#4A235A", "#D7BDE2"),  # 深紫底 + 浅紫文字
    "水晶头护套":("#512E5F", "#D2B4DE"),  # 深紫底 + 浅紫文字
    "散热":     ("#7B241C", "#F1948A"),  # 深红底 + 浅红文字
    "支架":     ("#1B4F72", "#AED6F1"),  # 深蓝底 + 浅蓝文字
    "模块":     ("#5B2C6F", "#D2B4DE"),  # 深紫底
}


def _make_image(path: str, text: str, bg_color: str, text_color: str,
                size: tuple = (800, 600)):
    """用 Pillow 生成一张带文字的纯色图片。"""
    img = Image.new("RGB", size, bg_color)
    draw = ImageDraw.Draw(img)

    # 尝试用系统字体
    font = None
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "C:/Windows/Fonts/arial.ttf",      # Arial fallback
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 36)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # 居中绘制文字
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size[0] - tw) // 2
    y = (size[1] - th) // 2
    draw.text((x, y), text, fill=text_color, font=font)

    # 底部加产品信息条
    info = text[:40]
    bbox2 = draw.textbbox((0, 0), info, font=font)
    iw, ih = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
    draw.text(((size[0] - iw) // 2, size[1] - ih - 40), info,
              fill=text_color, font=font)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", quality=85)


def generate_folders():
    """创建模拟 NAS 目录结构和假图片。"""
    print("=" * 60)
    print("生成模拟 NAS 目录和图片...")

    if os.path.exists(TEST_NAS):
        shutil.rmtree(TEST_NAS)

    total_images = 0

    for folder_path, subfolders in FOLDER_STRUCTURE.items():
        full_folder = os.path.join(TEST_NAS, folder_path)
        os.makedirs(full_folder, exist_ok=True)

        # 确定该文件夹属于哪个产品类别
        category = "转接卡"
        for kw in ["延长线", "硬盘盒", "水晶头", "散热", "支架", "模块"]:
            if kw in folder_path:
                category = kw
                break
        bg, fg = COLORS.get(category, ("#2C3E50", "#ECF0F1"))

        # 为每个子文件夹生成 2-4 张假图
        for sub in subfolders:
            sub_path = os.path.join(full_folder, sub)
            os.makedirs(sub_path, exist_ok=True)
            num_images = 3 if sub in ("中文", "英语") else 2
            for i in range(1, num_images + 1):
                fname = f"{i:02d}.jpg"
                file_path = os.path.join(sub_path, fname)
                label = f"{os.path.basename(folder_path)} / {sub} / {fname}"
                _make_image(file_path, label, bg, fg)
                total_images += 1

        print(f"  OK {folder_path} ({len(subfolders)} subdirs)")

    print(f"生成完成：{total_images} 张图片，{len(FOLDER_STRUCTURE)} 个产品文件夹")
    return total_images


def import_and_scan():
    """导入产品 CSV 并扫描 NAS 目录。"""
    from database import Database
    from config import Config
    from scanner import ScanWorker, ScanThread
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)

    cfg = Config()
    db = Database(cfg.db_path)
    db.init_db()
    db.clear_all()  # 清空旧数据（先建表保证表存在）

    # 导入产品 (v2.0: 4-tuple with image_url)
    db.import_products([(c, n, d, "") for c, n, d in TEST_PRODUCTS])
    # 为每个产品补充规格
    for code, name, desc in TEST_PRODUCTS:
        prod = db.get_product_by_code(code)
        if not prod:
            continue
        from search_tab import _extract_specs_from_name
        extracted = _extract_specs_from_name(name)
        specs = []
        for k, v in extracted.items():
            group = "物理参数" if k in ("长","宽","高","商品净重") else "基本规格"
            specs.append((group, k, v, "auto"))
        if specs:
            db.import_product_specs(prod["id"], specs)
    print(f"\n导入产品：{db.get_product_count()} 个（含规格）")

    # 设置 NAS 路径
    cfg.nas_root_path = TEST_NAS
    print(f"NAS 路径：{TEST_NAS}")

    # 扫描
    print("开始扫描索引...")
    worker = ScanWorker(db, TEST_NAS, incremental=False, last_scan_time=0.0)
    worker.run()  # 同步运行（数据量小）

    print(f"图片索引：{db.get_image_count()} 张")
    print(f"文件夹：{db.get_folder_count()} 个")
    print(f"产品关联：{db.get_link_count()} 组")

    # 验证搜索
    results = db.search_products("2233")
    print(f"\n验证搜索 '2233'：{len(results)} 个结果")
    for r in results[:3]:
        imgs = db.get_images_for_product(r["product_id"])
        print(f"  {r['full_code']} | {r['name'][:50]} | {len(imgs)} 张图")

    app.quit()


def main():
    parser = argparse.ArgumentParser(description="生成测试数据")
    parser.add_argument("--clean", action="store_true", help="清空旧数据")
    args = parser.parse_args()

    if args.clean:
        if os.path.exists(TEST_NAS):
            shutil.rmtree(TEST_NAS)
            print("已清空 test_nas/")
        db_path = os.path.join(DATA_DIR, "mysearch.db")
        if os.path.exists(db_path):
            os.remove(db_path)
            print("已清空数据库")

    # 1. 生成假图片
    generate_folders()

    # 2. 导入 + 扫描
    import_and_scan()

    print("\n" + "=" * 60)
    print("测试数据就绪！现在可以启动应用：")
    print(f"  cd {BASE_DIR}")
    print(f"  venv\\Scripts\\activate")
    print(f"  python main.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
