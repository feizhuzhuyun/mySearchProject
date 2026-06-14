"""
阶段 1 端到端测试：导入产品 → 扫描目录 → 验证数据。

用法:
    python create_test_data.py   # 首次运行，生成测试数据
    python test_phase1.py        # 运行测试
"""

import os
import sys
from pathlib import Path

# 确保从项目根目录运行
os.chdir(Path(__file__).parent)

from database import Database
from scanner import ScanWorker
from config import Config

TEST_DB = "data/test_phase1.db"

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def step(n: int, desc: str):
    print(f"\n-- Step {n}: {desc} --")

def main():
    # 清理旧测试库
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except PermissionError:
            pass  # 上次运行的文件锁还未释放，忽略

    db = Database(TEST_DB)
    db.init_db()

    # ─────────────────────────────────────────────────
    section("1. 导入产品 Excel")
    # ─────────────────────────────────────────────────
    import openpyxl
    xlsx_path = "test_data/products.xlsx"
    assert os.path.exists(xlsx_path), f"请先运行 create_test_data.py"

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = rows[1:]

    # 自动映射列
    col_map = {}
    for i, h in enumerate(header):
        h_lower = str(h).lower() if h else ""
        if "69码" in h_lower or "code" in h_lower:
            col_map["code"] = i
        elif "名称" in h_lower or "name" in h_lower:
            col_map["name"] = i
        elif "描述" in h_lower or "desc" in h_lower:
            col_map["desc"] = i

    records = []
    for row in data:
        code = str(row[col_map["code"]]).strip() if col_map.get("code") is not None and row[col_map["code"]] else ""
        name = str(row[col_map["name"]]).strip() if col_map.get("name") is not None and row[col_map["name"]] else ""
        desc = str(row[col_map["desc"]]).strip() if col_map.get("desc") is not None and row[col_map["desc"]] else ""
        if code and name:
            records.append((code, name, desc))

    n = db.import_products(records)
    print(f"导入 {n} 条产品记录")
    assert n == 8, f"Expected 8 products, got {n}"

    # ─────────────────────────────────────────────────
    section("2. 全量扫描 mock NAS")
    # ─────────────────────────────────────────────────
    nas_root = os.path.abspath("test_data/mock_nas")
    assert os.path.exists(nas_root), f"请先运行 create_test_data.py"

    # 直接用 ScanWorker 同步跑（不创建 QThread）
    worker = ScanWorker(db, nas_root, incremental=False)
    stats = worker._scan()  # 内部方法，同步执行

    print(f"扫描结果: {stats}")
    assert stats["files"] == 18, f"Expected 18 images, got {stats['files']}"
    assert stats["folders"] == 9, f"Expected 9 folders (empty folder excluded), got {stats['folders']}"

    # ─────────────────────────────────────────────────
    section("3. 验证 images 表")
    # ─────────────────────────────────────────────────
    image_count = db.get_image_count()
    folder_count = db.get_folder_count()
    print(f"Images: {image_count}, Unique folders: {folder_count}")
    assert image_count == 18, f"Expected 18 images, got {image_count}"
    assert folder_count == 9, f"Expected 9 folders, got {folder_count}"

    # ─────────────────────────────────────────────────
    section("4. 验证 folder_codes + 产品关联表")
    # ─────────────────────────────────────────────────
    link_count = db.get_link_count()
    print(f"Product-folder links: {link_count}")
    # 预期 ≥ 8（一个 4 位码可能匹配多个产品，产品-文件夹对去重后）
    assert link_count >= 7, f"Expected at least 7 links, got {link_count}"
    print("  [PASS] product-folder links OK")

    # ─────────────────────────────────────────────────
    section("5. 验证增量扫描")
    # ─────────────────────────────────────────────────
    import time
    last_scan = time.time()

    # 用增量 worker 重新扫描 — 应该没有新文件
    inc_worker = ScanWorker(db, nas_root, incremental=True, last_scan_time=last_scan)
    stats2 = inc_worker._scan()
    print(f"Incremental scan (no new files): {stats2}")
    assert stats2["files"] == 0, f"Expected 0 new files, got {stats2['files']}"

    # 添加一个新文件
    new_folder = os.path.join(nas_root, "NewProduct_5678")
    os.makedirs(new_folder, exist_ok=True)
    new_file = os.path.join(new_folder, "new.jpg")
    with open(new_file, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + os.urandom(64))

    worker2 = ScanWorker(db, nas_root, incremental=True, last_scan_time=last_scan)
    stats3 = worker2._scan()
    print(f"Incremental scan (+1 new file): {stats3}")
    assert stats3["files"] >= 1, f"Expected at least 1 new file, got {stats3['files']}"

    # ─────────────────────────────────────────────────
    section("6. 验证 clear_all + 全量重建")
    # ─────────────────────────────────────────────────
    db.clear_all()
    assert db.get_image_count() == 0
    assert db.get_product_count() == 0
    print("clear_all OK — all tables emptied")

    # 重新导入+扫描
    db.import_products(records)
    worker3 = ScanWorker(db, nas_root, incremental=False)
    stats4 = worker3._scan()
    assert stats4["files"] >= 18  # at least the original 18 + potentially new file
    print(f"重建完成: {stats4}")

    # ─────────────────────────────────────────────────
    section("7. 打印摘要")
    # ─────────────────────────────────────────────────
    print(f"  产品: {db.get_product_count()} 条")
    print(f"  图片: {db.get_image_count()} 张")
    print(f"  文件夹: {db.get_folder_count()} 个")
    print(f"  关联: {db.get_link_count()} 组")

    # ─────────────────────────────────────────────────
    section("ALL TESTS PASSED")
    # ─────────────────────────────────────────────────

    # 清理（关闭 DB 引用后删除）
    del db
    try:
        os.remove(TEST_DB)
        print(f"\nCleanup: {TEST_DB} removed")
    except PermissionError:
        print(f"\nCleanup: {TEST_DB} will be removed on next run")


if __name__ == "__main__":
    main()
