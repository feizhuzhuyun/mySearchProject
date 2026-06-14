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
                    description  TEXT    NOT NULL DEFAULT ''
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

                CREATE UNIQUE INDEX IF NOT EXISTS idx_folder_codes_unique
                    ON folder_codes(folder_path, code_tail);

                CREATE INDEX IF NOT EXISTS idx_folder_codes_code_tail
                    ON folder_codes(code_tail);

                CREATE TABLE IF NOT EXISTS product_folder_link (
                    product_id  INTEGER NOT NULL,
                    folder_path TEXT    NOT NULL,
                    PRIMARY KEY (product_id, folder_path)
                );

                CREATE INDEX IF NOT EXISTS idx_pfl_folder_path
                    ON product_folder_link(folder_path);

                CREATE TABLE IF NOT EXISTS product_attrs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id   INTEGER NOT NULL,
                    attr_name  TEXT    NOT NULL,
                    attr_value TEXT    NOT NULL,
                    UNIQUE(image_id, attr_name, attr_value)
                );

                CREATE INDEX IF NOT EXISTS idx_product_attrs_name
                    ON product_attrs(attr_name);
                CREATE INDEX IF NOT EXISTS idx_product_attrs_image
                    ON product_attrs(image_id);
            """)

            # ── 迁移：已有表的增量更新 ──
            # code_tail 列
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN code_tail TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass

            # images 表阶段 3 预置列（每列都有 DEFAULT，不加 ALTER 时不影响现有数据）
            _img_cols = [
                ("feature_extracted", "INTEGER NOT NULL DEFAULT 0"),
                ("thumbnail_path",    "TEXT    NOT NULL DEFAULT ''"),
                ("ocr_extracted",     "INTEGER NOT NULL DEFAULT 0"),
                ("phash",             "INTEGER NOT NULL DEFAULT 0"),
                ("width",             "INTEGER NOT NULL DEFAULT 0"),
                ("height",            "INTEGER NOT NULL DEFAULT 0"),
                ("file_size",         "INTEGER NOT NULL DEFAULT 0"),
            ]
            for col_name, col_def in _img_cols:
                try:
                    conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

            # 回填已有产品的 code_tail（移出循环，只执行一次）
            conn.execute(
                "UPDATE products SET code_tail = substr(full_code, -4) "
                "WHERE code_tail = '' AND length(full_code) >= 4"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_code_tail "
                "ON products(code_tail)"
            )

    # ── 产品操作 ─────────────────────────────────────────────────
    def import_products(self, rows: list[tuple[str, str, str]]) -> int:
        """
        批量导入产品。rows 每项为 (full_code, name, description)。
        自动提取 code_tail（69码后四位）。
        """
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO products
                      (full_code, name, description, code_tail)
                   VALUES (?, ?, ?, substr(?, -4))""",
                [(c, n, d, c) for c, n, d in rows],
            )
        return len(rows)

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
            elif len(query) >= 13:
                # 13 位：完整69码精确匹配（利用 UNIQUE 索引）
                rows = conn.execute(
                    """SELECT DISTINCT pfl.folder_path,
                              (SELECT folder_name FROM images
                               WHERE folder_path = pfl.folder_path LIMIT 1
                              ) AS folder_name,
                              p.id AS product_id, p.name AS product_name,
                              p.full_code
                       FROM products p
                       JOIN product_folder_link pfl ON pfl.product_id = p.id
                       WHERE p.full_code = ?
                       ORDER BY p.full_code""",
                    (query,),
                ).fetchall()
            else:
                # 1-3 位或 5-12 位：full_code 后缀模糊匹配
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
    def clear_index(self):
        """清空索引数据（保留产品表）。用于重建索引。"""
        with self._connect() as conn:
            conn.executescript("""
                DELETE FROM product_folder_link;
                DELETE FROM folder_codes;
                DELETE FROM images;
            """)

    def clear_all(self):
        """清空所有数据表（包括产品表，保留表结构）。"""
        with self._connect() as conn:
            conn.executescript("""
                DELETE FROM product_folder_link;
                DELETE FROM folder_codes;
                DELETE FROM images;
                DELETE FROM products;
            """)
