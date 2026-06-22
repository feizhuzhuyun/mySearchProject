"""
SQLite 数据库层 — 产品、图片索引、文件夹码、关联表。

使用方式:
    db = Database("path/to/mysearch.db")
    db.init_db()
    db.import_products([(full_code, name, desc), ...])
"""

import os
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# 单例数据库
# ---------------------------------------------------------------------------
class Database:
    """管理 mysearch 的所有 SQLite 数据。"""

    def __init__(self, db_path: str = ""):
        if not db_path:
            import config
            db_path = config.DEFAULT_CONFIG["db_path"]
        self._db_path = db_path

    # ── 连接管理 ─────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10)  # 10s 超时防 busy
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── 建表 / 迁移 ───────────────────────────────────────────────
    def init_db(self):
        """创建所有表 + 执行增量迁移。"""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_code    TEXT    NOT NULL UNIQUE,
                    name         TEXT    NOT NULL DEFAULT '',
                    description  TEXT    NOT NULL DEFAULT '',
                    data_source  TEXT    NOT NULL DEFAULT 'csv'
                );

                CREATE TABLE IF NOT EXISTS images (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_unc       TEXT    NOT NULL UNIQUE,
                    folder_path    TEXT    NOT NULL,
                    folder_name    TEXT    NOT NULL,
                    file_name      TEXT    NOT NULL,
                    ocr_text       TEXT    NOT NULL DEFAULT '',
                    last_modified  INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_images_folder_path
                    ON images(folder_path);
                CREATE INDEX IF NOT EXISTS idx_images_folder_name
                    ON images(folder_name);

                CREATE TABLE IF NOT EXISTS folder_codes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    code_tail   TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_folder_codes_code_tail
                    ON folder_codes(code_tail);
                CREATE INDEX IF NOT EXISTS idx_folder_codes_folder_path
                    ON folder_codes(folder_path);

                CREATE TABLE IF NOT EXISTS product_folder_link (
                    product_id  INTEGER NOT NULL,
                    folder_path TEXT    NOT NULL,
                    PRIMARY KEY (product_id, folder_path)
                );

                CREATE INDEX IF NOT EXISTS idx_pfl_folder_path
                    ON product_folder_link(folder_path);

                -- v2.0: 产品规格表（动态 key-value）
                CREATE TABLE IF NOT EXISTS product_specs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id  INTEGER NOT NULL,
                    spec_group  TEXT    NOT NULL DEFAULT '',
                    spec_name   TEXT    NOT NULL,
                    spec_value  TEXT    NOT NULL DEFAULT '',
                    source      TEXT    NOT NULL DEFAULT 'csv',
                    FOREIGN KEY (product_id) REFERENCES products(id)
                );

                CREATE INDEX IF NOT EXISTS idx_specs_product
                    ON product_specs(product_id);
            """)

            # ── 迁移：添加 data_source 列（三数据源独立追踪） ──
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN data_source TEXT NOT NULL DEFAULT 'csv'"
                )
            except sqlite3.OperationalError:
                pass

            # ── 迁移：添加 code_tail 列 ──
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN code_tail TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass

            # ── 迁移：添加 main_image_local 列（CSV 图片本地缓存路径） ──
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN main_image_local TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass

            # ── 迁移：添加 main_image_url 列（CSV 原始图片 URL） ──
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN main_image_url TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass

            # 回填已有产品的 code_tail
            conn.execute(
                "UPDATE products SET code_tail = substr(full_code, -4) "
                "WHERE code_tail = '' AND length(full_code) >= 4"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_code_tail "
                "ON products(code_tail)"
            )

    # ── 产品操作 ─────────────────────────────────────────────────
    def import_products(self, rows: list[tuple]) -> int:
        """
        批量导入产品。rows 每项为:
          (full_code, name, description, main_image_url)

        v2.0: 支持可选 main_image_url。
        自动提取 code_tail（69码后四位）。
        已存在的产品 UPDATE 而非 REPLACE（避免外键冲突）。
        """
        count = 0
        with self._connect() as conn:
            for r in rows:
                code, name, desc = r[0], r[1], r[2]
                img_url = r[3] if len(r) > 3 else ""
                existing = conn.execute(
                    "SELECT id FROM products WHERE full_code = ?", (code,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE products SET name=?, description=?, main_image_url=? WHERE id=?",
                        (name, desc, img_url, existing[0]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO products
                              (full_code, name, description, code_tail, main_image_url, data_source)
                           VALUES (?, ?, ?, substr(?, -4), ?, 'csv')""",
                        (code, name, desc, code, img_url),
                    )
                count += 1
        return count

    # ── 产品规格操作 ─────────────────────────────────────────────
    def import_product_specs(self, product_id: int, specs: list[tuple]):
        """
        批量导入产品规格。specs 每项: (spec_group, spec_name, spec_value, source)
        先删后插（幂等）。
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM product_specs WHERE product_id = ?", (product_id,))
            conn.executemany(
                """INSERT INTO product_specs (product_id, spec_group, spec_name, spec_value, source)
                   VALUES (?, ?, ?, ?, ?)""",
                [(product_id, g, n, v, s) for g, n, v, s in specs],
            )
        return len(specs)

    def get_product_specs(self, product_id: int) -> list[dict]:
        """获取某产品的所有规格（按分组排序）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT spec_group, spec_name, spec_value, source
                   FROM product_specs
                   WHERE product_id = ?
                   ORDER BY spec_group, id""",
                (product_id,),
            ).fetchall()
        return [
            {"group": r[0], "name": r[1], "value": r[2], "source": r[3]}
            for r in rows
        ]

    def get_product_by_code(self, full_code: str) -> dict | None:
        """按 full_code 查找产品。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, full_code, name, description, code_tail, main_image_url, main_image_local "
                "FROM products WHERE full_code = ?",
                (full_code,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "full_code": row[1], "name": row[2],
            "description": row[3], "code_tail": row[4],
            "main_image_url": row[5] or "", "main_image_local": row[6] or "",
        }

    def set_product_main_image_local(self, product_id: int, local_path: str):
        """更新产品的主图本地缓存路径。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE products SET main_image_local = ? WHERE id = ?",
                (local_path, product_id),
            )

    def get_product_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # ── 图片操作 ─────────────────────────────────────────────────
    def import_images(self, rows: list[tuple]) -> int:
        """
        批量导入图片记录。
        rows 每项: (full_unc, folder_path, folder_name, file_name, last_modified)
        """
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO images
                      (full_unc, folder_path, folder_name, file_name, last_modified)
                   VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    def get_image_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    def get_folder_count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(DISTINCT folder_path) FROM images"
            ).fetchone()[0]

    # ── 文件夹码操作 ─────────────────────────────────────────────
    def import_folder_codes(self, rows: list[tuple[str, str]]) -> int:
        """
        批量导入文件夹码。rows 每项: (folder_path, code_tail)
        """
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO folder_codes (folder_path, code_tail)
                   VALUES (?, ?)""",
                rows,
            )
        return len(rows)

    # ── 关联重建 ─────────────────────────────────────────────────
    def rebuild_links(self):
        """根据 folder_codes 与 products 的后四位匹配，重建关联表。
        使用 code_tail 列上的索引做等值 JOIN，替代 LIKE 全表扫描。
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM product_folder_link")
            conn.execute("""
                INSERT OR IGNORE INTO product_folder_link (product_id, folder_path)
                SELECT DISTINCT p.id, fc.folder_path
                FROM folder_codes fc
                JOIN products p ON p.code_tail = fc.code_tail
            """)

    def get_link_count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM product_folder_link"
            ).fetchone()[0]

    # ── 搜索 ─────────────────────────────────────────────────────
    def search_folders_by_code_tail(self, query: str) -> list[dict]:
        """
        69码渐进匹配：
        - 1-3 位：products.full_code 后缀模糊
        - 4 位：code_tail 精确匹配（索引）
        - 5+ 位：products.full_code 后缀模糊，逐步收敛
        """
        with self._connect() as conn:
            if len(query) == 4:
                # 精确后四位匹配（利用 code_tail 索引）
                rows = conn.execute(
                    """SELECT DISTINCT fc.folder_path,
                              (SELECT folder_name FROM images
                               WHERE folder_path = fc.folder_path LIMIT 1
                              ) AS folder_name,
                              p.id AS product_id, p.name AS product_name,
                              p.full_code
                       FROM folder_codes fc
                       LEFT JOIN product_folder_link pfl
                         ON pfl.folder_path = fc.folder_path
                       LEFT JOIN products p ON p.id = pfl.product_id
                       WHERE fc.code_tail = ?
                       ORDER BY fc.folder_path""",
                    (query,),
                ).fetchall()
            else:
                # 1-3 位或 5+ 位：full_code 后缀模糊匹配
                tail = query[-4:] if len(query) > 4 else query
                rows = conn.execute(
                    """SELECT DISTINCT pfl.folder_path,
                              (SELECT folder_name FROM images
                               WHERE folder_path = pfl.folder_path LIMIT 1
                              ) AS folder_name,
                              p.id AS product_id, p.name AS product_name,
                              p.full_code
                       FROM products p
                       JOIN product_folder_link pfl ON pfl.product_id = p.id
                       WHERE p.full_code LIKE ?
                       ORDER BY p.full_code""",
                    (f"%{query}",),
                ).fetchall()
        return [
            {
                "folder_path": r[0],
                "folder_name": r[1] or "",
                "product_id": r[2],
                "product_name": r[3] or "",
                "full_code": r[4] or "",
            }
            for r in rows
        ]

    def search_folders_by_keyword(self, keyword: str) -> list[dict]:
        """
        关键字搜索文件夹名，同时返回关联产品信息。
        排序：精确匹配 > 包含关键字 > 部分匹配，有产品信息优先。
        """
        like = f"%{keyword}%"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT i.folder_path, i.folder_name,
                          COUNT(*) AS image_count,
                          p.id AS product_id, p.name AS product_name,
                          p.full_code
                   FROM images i
                   LEFT JOIN product_folder_link pfl
                     ON pfl.folder_path = i.folder_path
                   LEFT JOIN products p ON p.id = pfl.product_id
                   WHERE i.folder_name LIKE ?
                   GROUP BY i.folder_path
                   ORDER BY
                     CASE WHEN i.folder_name = ? THEN 0
                          WHEN i.folder_name LIKE ? THEN 1
                          ELSE 2
                     END,
                     image_count DESC""",
                (like, keyword, f"%{keyword}%"),
            ).fetchall()
        return [
            {
                "folder_path": r[0],
                "folder_name": r[1],
                "image_count": r[2],
                "product_id": r[3],
                "product_name": r[4] or "",
                "full_code": r[5] or "",
            }
            for r in rows
        ]

    def get_images_by_folder(self, folder_path: str) -> list[dict]:
        """获取某文件夹下所有图片记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, full_unc, folder_path, folder_name,
                          file_name, last_modified
                   FROM images
                   WHERE folder_path = ?
                   ORDER BY file_name""",
                (folder_path,),
            ).fetchall()
        return [
            {
                "id": r[0], "full_unc": r[1], "folder_path": r[2],
                "folder_name": r[3], "file_name": r[4],
                "last_modified": r[5],
            }
            for r in rows
        ]

    def get_folders_for_product(self, product_id: int) -> list[dict]:
        """获取某产品关联的所有文件夹。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT i.folder_path, i.folder_name
                   FROM product_folder_link pfl
                   JOIN images i ON i.folder_path = pfl.folder_path
                   WHERE pfl.product_id = ?
                   ORDER BY i.folder_name""",
                (product_id,),
            ).fetchall()
        return [{"folder_path": r[0], "folder_name": r[1]} for r in rows]

    # ── 产品级搜索（v2.0 UI 用）────────────────────────────────────
    def search_products(self, query: str) -> list[dict]:
        """
        搜索产品 — 返回产品级结果（含关联文件夹信息）。
        每个结果 = 一个产品 / SKU。
        """
        with self._connect() as conn:
            if query.isdigit():
                # 69码渐进匹配
                if len(query) == 4:
                    rows = conn.execute(
                        """SELECT p.id, p.full_code, p.name, p.description, p.code_tail,
                                  (SELECT folder_path FROM product_folder_link
                                   WHERE product_id = p.id LIMIT 1) AS folder_path,
                                  (SELECT COUNT(DISTINCT folder_path) FROM product_folder_link
                                   WHERE product_id = p.id) AS folder_count,
                                  (SELECT COUNT(*) FROM images i
                                   JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                                   WHERE pfl.product_id = p.id) AS image_count
                           FROM products p
                           WHERE p.code_tail = ?
                           ORDER BY p.full_code""",
                        (query,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT p.id, p.full_code, p.name, p.description, p.code_tail,
                                  (SELECT folder_path FROM product_folder_link
                                   WHERE product_id = p.id LIMIT 1) AS folder_path,
                                  (SELECT COUNT(DISTINCT folder_path) FROM product_folder_link
                                   WHERE product_id = p.id) AS folder_count,
                                  (SELECT COUNT(*) FROM images i
                                   JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                                   WHERE pfl.product_id = p.id) AS image_count
                           FROM products p
                           WHERE p.full_code LIKE ?
                           ORDER BY p.full_code""",
                        (f"%{query}",),
                    ).fetchall()
            else:
                # 关键字搜索 — 优先产品名匹配，其次关联文件夹名匹配
                like = f"%{query}%"
                rows = conn.execute(
                    """SELECT p.id, p.full_code, p.name, p.description, p.code_tail,
                              (SELECT folder_path FROM product_folder_link
                               WHERE product_id = p.id LIMIT 1) AS folder_path,
                              (SELECT COUNT(DISTINCT folder_path) FROM product_folder_link
                               WHERE product_id = p.id) AS folder_count,
                              (SELECT COUNT(*) FROM images i
                               JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                               WHERE pfl.product_id = p.id) AS image_count
                       FROM products p
                       WHERE p.name LIKE ? OR p.description LIKE ?
                          OR p.full_code LIKE ?
                          OR p.id IN (
                              SELECT DISTINCT pfl.product_id
                              FROM product_folder_link pfl
                              JOIN images i ON i.folder_path = pfl.folder_path
                              WHERE i.folder_name LIKE ?
                          )
                       ORDER BY
                         CASE WHEN p.name LIKE ? THEN 0
                              WHEN p.full_code LIKE ? THEN 1
                              WHEN p.description LIKE ? THEN 2
                              ELSE 3
                         END,
                         p.full_code""",
                    (like, like, like, like, like, like, like),
                ).fetchall()
        return [
            {
                "product_id": r[0],
                "full_code": r[1],
                "name": r[2] or "",
                "description": r[3] or "",
                "code_tail": r[4] or "",
                "folder_path": r[5] or "",
                "folder_count": r[6] or 0,
                "image_count": r[7] or 0,
            }
            for r in rows
        ]

    def get_images_for_product(self, product_id: int) -> list[dict]:
        """获取某产品关联的所有图片（跨所有关联文件夹）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT i.id, i.full_unc, i.folder_path, i.folder_name,
                          i.file_name, i.last_modified
                   FROM images i
                   JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                   WHERE pfl.product_id = ?
                   ORDER BY i.folder_name, i.file_name""",
                (product_id,),
            ).fetchall()
        return [
            {
                "id": r[0], "full_unc": r[1], "folder_path": r[2],
                "folder_name": r[3], "file_name": r[4],
                "last_modified": r[5],
            }
            for r in rows
        ]

    def get_product_main_image_path(self, product_id: int) -> str:
        """
        获取某产品的主图路径。
        优先级：CSV 本地缓存 > NAS 扫描图片 > CSV 远程 URL（仅作 fallback 标记）。
        """
        with self._connect() as conn:
            # 1. 优先 CSV 导入时下载的本地缓存
            row = conn.execute(
                "SELECT main_image_local FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
            if row and row[0]:
                return row[0]

            # 2. 回退到 NAS 扫描的第一张关联图片
            row = conn.execute(
                """SELECT i.full_unc
                   FROM images i
                   JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                   WHERE pfl.product_id = ?
                   ORDER BY i.folder_name, i.file_name
                   LIMIT 1""",
                (product_id,),
            ).fetchone()
            if row and row[0]:
                return row[0]

        return ""

    def search_products_by_code_tail(self, tail: str) -> list[dict]:
        """按69码后四位搜索产品（利用 code_tail 索引）。"""
        tail = tail[-4:]
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, full_code, name, description
                   FROM products
                   WHERE code_tail = ?
                   ORDER BY full_code""",
                (tail,),
            ).fetchall()
        return [
            {"id": r[0], "full_code": r[1], "name": r[2], "description": r[3]}
            for r in rows
        ]

    # ── 清空 / 重置 ──────────────────────────────────────────────
    def export_jsonl(self, output_path: str) -> int:
        """将当前产品数据导出为 JSONL 格式。"""
        import json
        count = 0
        with self._connect() as conn:
            # 获取所有产品
            products = conn.execute(
                "SELECT id, full_code, name, description, code_tail, main_image_url, data_source "
                "FROM products ORDER BY full_code"
            ).fetchall()

            # 按 group 聚合（简化：相同 folder_path 的视为同组）
            folder_map: dict[str, list] = {}
            for p in products:
                pid = p[0]
                folders = conn.execute(
                    "SELECT folder_path FROM product_folder_link WHERE product_id = ?",
                    (pid,),
                ).fetchall()
                key = folders[0][0] if folders else f"nogroup_{pid}"
                folder_map.setdefault(key, []).append(p)

            with open(output_path, "w", encoding="utf-8") as f:
                for folder_path, prods in folder_map.items():
                    # 获取该文件夹的图片集信息
                    img_rows = conn.execute(
                        "SELECT DISTINCT folder_name FROM images WHERE folder_path = ?",
                        (folder_path,),
                    ).fetchall()

                    group_id = f"GROUP-{prods[0][4]}" if prods else "UNKNOWN"
                    obj = {
                        "group_id": group_id,
                        "folder_path": folder_path,
                        "folder_name": os.path.basename(folder_path),
                        "category": "",
                        "status": "active",
                        "products": [],
                        "image_sets": [
                            {"path": r[0], "set_type": "language", "language": "zh"}
                            for r in img_rows
                        ],
                        "data_source": "export",
                        "llm_model": "",
                        "llm_timestamp": "",
                    }
                    for p in prods:
                        pid, code, name, desc, tail, img_url, source = p
                        specs = self.get_product_specs(pid)
                        spec_dict = {}
                        for s in specs:
                            spec_dict[s["name"]] = s["value"]
                        obj["products"].append({
                            "product_id": code,
                            "name": name,
                            "full_code": code if len(code) == 13 and code.isdigit() else "",
                            "code_tail": tail,
                            "sku_custom": code if not (len(code) == 13 and code.isdigit()) else "",
                            "is_primary": True,
                            "specs": spec_dict,
                            "tags": [],
                        })
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    count += 1
        return count

    def get_product_source_matrix(self) -> list[dict]:
        """
        返回每个产品的三源数据完整性矩阵。
        每项: {product_id, full_code, name, data_source,
               csv_specs, llm_specs, auto_specs, image_count, folder_count}
        csv_specs = source='csv' 的 specs
        auto_specs = source='auto' 的 specs（从名称提取）
        llm_specs = source='llm' 的 specs（来自知识库）
        """
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT p.id, p.full_code, p.name, p.data_source,
                       (SELECT COUNT(*) FROM product_specs WHERE product_id = p.id AND source='csv') AS csv_specs,
                       (SELECT COUNT(*) FROM product_specs WHERE product_id = p.id AND source='llm') AS llm_specs,
                       (SELECT COUNT(*) FROM product_specs WHERE product_id = p.id AND source='auto') AS auto_specs,
                       (SELECT COUNT(DISTINCT i.id) FROM images i
                        JOIN product_folder_link pfl ON i.folder_path = pfl.folder_path
                        WHERE pfl.product_id = p.id) AS image_count,
                       (SELECT COUNT(DISTINCT pfl.folder_path) FROM product_folder_link pfl
                        WHERE pfl.product_id = p.id) AS folder_count
                FROM products p
                ORDER BY p.full_code
            """).fetchall()
        return [
            {
                "product_id": r[0], "full_code": r[1], "name": r[2],
                "data_source": r[3], "csv_specs": r[4], "llm_specs": r[5],
                "auto_specs": r[6], "image_count": r[7] or 0, "folder_count": r[8] or 0,
            }
            for r in rows
        ]

    def clear_source_data(self, source: str) -> dict:
        """
        清除指定来源的数据，不影响其他来源。
        source: 'csv' / 'llm' / 'manual'
        返回 {"products": N, "specs": N}
        """
        stats = {"products": 0, "specs": 0}
        with self._connect() as conn:
            # 找到该来源的产品 ID
            pids = [r[0] for r in conn.execute(
                "SELECT id FROM products WHERE data_source = ?", (source,)
            ).fetchall()]
            if pids:
                placeholders = ",".join("?" * len(pids))
                conn.execute(
                    f"DELETE FROM product_specs WHERE product_id IN ({placeholders})",
                    pids,
                )
                stats["specs"] = conn.total_changes
                conn.execute(
                    f"DELETE FROM product_folder_link WHERE product_id IN ({placeholders})",
                    pids,
                )
                conn.execute(
                    f"DELETE FROM products WHERE id IN ({placeholders})",
                    pids,
                )
                stats["products"] = len(pids)
        return stats

    def clear_index(self):
        """清空索引数据（保留产品表）。用于重建索引。"""
        with self._connect() as conn:
            conn.executescript("""
                DELETE FROM product_folder_link;
                DELETE FROM folder_codes;
                DELETE FROM images;
            """)

    def import_jsonl(self, jsonl_path: str) -> dict:
        """
        从 products.jsonl 导入知识库数据。
        返回 {"products": N, "specs": N, "errors": [...]}
        """
        import json
        stats = {"products": 0, "specs": 0, "errors": []}

        if not os.path.exists(jsonl_path):
            stats["errors"].append(f"文件不存在: {jsonl_path}")
            return stats

        with self._connect() as conn:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as e:
                        stats["errors"].append(f"第{line_no}行 JSON 解析失败: {e}")
                        continue

                    products = obj.get("products", [])
                    for prod in products:
                        code = prod.get("full_code", "") or prod.get("sku_custom", "")
                        name = prod.get("name", "")
                        if not code or not name:
                            continue

                        # 插入/更新产品（避免外键冲突：先查存在则更新）
                        existing = conn.execute(
                            "SELECT id FROM products WHERE full_code = ?", (code,)
                        ).fetchone()
                        if existing:
                            conn.execute(
                                "UPDATE products SET name=?, description=?, main_image_url=? WHERE id=?",
                                (name, prod.get("description", ""), prod.get("main_image_url", ""), existing[0]),
                            )
                            pid = existing[0]
                        else:
                            conn.execute(
                                """INSERT INTO products
                                   (full_code, name, description, code_tail, main_image_url, data_source)
                                   VALUES (?, ?, ?, substr(?, -4), ?, 'llm')""",
                                (code, name, prod.get("description", ""),
                                 code, prod.get("main_image_url", "")),
                            )
                            pid = conn.execute(
                                "SELECT id FROM products WHERE full_code = ?", (code,)
                            ).fetchone()[0]
                        stats["products"] += 1

                        # 导入 common_specs（组级共享规格）
                        common = obj.get("common_specs", {})
                        for group, fields in common.items():
                            if isinstance(fields, dict):
                                for k, v in fields.items():
                                    conn.execute(
                                        """INSERT OR REPLACE INTO product_specs
                                           (product_id, spec_group, spec_name, spec_value, source)
                                           VALUES (?, ?, ?, ?, 'llm')""",
                                        (pid, group, k, str(v)),
                                    )
                                    stats["specs"] += 1

                        # 导入变体独有规格
                        for k, v in prod.get("specs", {}).items():
                            if isinstance(v, dict):
                                for sk, sv in v.items():
                                    conn.execute(
                                        """INSERT OR REPLACE INTO product_specs
                                           (product_id, spec_group, spec_name, spec_value, source)
                                           VALUES (?, ?, ?, ?, 'llm')""",
                                        (pid, k, sk, str(sv)),
                                    )
                                    stats["specs"] += 1
                            else:
                                conn.execute(
                                    """INSERT OR REPLACE INTO product_specs
                                       (product_id, spec_group, spec_name, spec_value, source)
                                       VALUES (?, '基本规格', ?, ?, 'llm')""",
                                    (pid, k, str(v)),
                                )
                                stats["specs"] += 1

        return stats

    def clear_all(self):
        """清空所有数据表（包括产品表，保留表结构）。按外键依赖顺序删除。"""
        with self._connect() as conn:
            conn.executescript("""
                DELETE FROM product_specs;
                DELETE FROM product_folder_link;
                DELETE FROM folder_codes;
                DELETE FROM images;
                DELETE FROM products;
            """)
