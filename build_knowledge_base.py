"""
知识库构建工具 — 独立脚本，与主应用解耦。

用途：用 LLM（DeepSeek / GPT-4o 等）分析 NAS 产品图片目录，输出 products.jsonl。

用法：
    python build_knowledge_base.py --input K:\1.图片 --output products.jsonl --model deepseek-v3

也可作为模块导入：
    from build_knowledge_base import build_prompt, PRODUCT_JSONL_SCHEMA

设计理念：
    - 知识库构建是"重活"（有网络、有成本、一次性），与扫描器解耦
    - 主应用通过"导入知识库"按钮读取 products.jsonl，合并到 SQLite
    - 可复用于不同的 NAS 目录、不同的 AI 模型
"""

import os, sys, json, argparse
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════
# JSONL 输出规范（供 LLM 和导入程序共同遵守）
# ═══════════════════════════════════════════════════════════════════
PRODUCT_JSONL_SCHEMA = """
{
  "group_id": "产品组唯一ID（推荐格式：品类缩写-后四位码，如 ADAPTER-2233）",
  "folder_name": "产品根文件夹名（原始）",
  "folder_path": "从 NAS 根目录起的相对路径",
  "category": "一级分类（转接卡/延长线/硬盘盒/散热/水晶头/...）",
  "sub_category": "二级分类（可选，如 PCIe转M.2）",
  "status": "active / discontinued / unsold",
  "common_specs": {
    "任意规格名": "组内所有变体共享的规格值",
    "...": "..."
  },
  "products": [
    {
      "product_id": "SKU 唯一标识（优先用 69 码，无 69 码用自定义 SKU）",
      "name": "产品名称（含颜色/规格等区分信息）",
      "full_code": "完整 69 码（13 位数字），无则填 ''",
      "code_tail": "69 码后 4 位，无则填 ''",
      "sku_custom": "自定义 SKU（非 69 码时填写）",
      "main_image_url": "CSV 中的主图 URL（可选）",
      "is_primary": true,
      "matching_specs": {"颜色": "黑色"},
      "specs": {"任意规格名": "该变体独有的规格值"},
      "tags": ["搜索关键词1", "关键词2", "..."]
    }
  ],
  "image_sets": [
    {"path": "中文", "set_type": "language", "language": "zh", "is_primary": true},
    {"path": "英语", "set_type": "language", "language": "en"},
    {"path": "实拍图", "set_type": "real"},
    {"path": "渲染图", "set_type": "render"}
  ],
  "shared_images": [
    {"file": "包装图.jpg", "type": "package", "shared_by": "all"}
  ],
  "data_source": "llm",
  "llm_model": "模型名",
  "llm_timestamp": "ISO 8601 时间"
}
"""


# ═══════════════════════════════════════════════════════════════════
# LLM 提示词
# ═══════════════════════════════════════════════════════════════════
def build_prompt(folder_path: str, folder_structure: str, language_priority: str = "zh,en") -> str:
    """
    构建 LLM 分析提示词。

    参数：
        folder_path: NAS 根目录路径
        folder_structure: 预扫描的目录结构文本（可用 os.walk 生成）
        language_priority: 优先语言代码，逗号分隔
    """
    return f"""你是一个电子产品图片目录分析专家。请分析以下 NAS 目录结构，输出结构化的产品知识库 JSONL。

## 分析规则

### 1. 识别产品根文件夹
每个包含子文件夹（如"中文"/"英语"/"实拍图"等）的目录，视为一个产品根文件夹。
产品根文件夹 = 一个 product_group。

### 2. 识别 SKU 变体
从文件夹名中提取：
- **69 码后四位**：所有 4 位连续数字。如 "2233 2240" 表示两个 SKU
- **型号**：如 "型号：P717""型号：蜻蜓x1"
- **颜色**：黑色/白色/红色/蓝色/绿色/黄色/青色/灰色
- **规格关键词**：X1/X4/X16/M.2/NVMe/SATA/2280/2242/22110/50CM/20CM/PCIe 4.0/PCIe 5.0
- 如果文件夹名不含多个 SKU 标识 → 整个文件夹 = 1 个产品

### 3. 识别图片集（image_set）
扫描产品根文件夹下的子文件夹名：
| 文件夹包含关键词 | set_type | language | 说明 |
|-----------------|----------|----------|------|
| 中文            | language | zh       | 优先 |
| 英语/英文       | language | en       | 优先 |
| 西班牙语        | language | es       | 优先 |
| 俄语            | language | ru       | 备选 |
| 韩语            | language | ko       | 备选 |
| 印尼语          | language | id       | 备选 |
| 泰语            | language | th       | 备选 |
| 法文            | language | fr       | 备选 |
| 渲染图          | render   | -        | 可选 |
| 实拍图          | real     | -        | 建议 |
| 主图            | primary  | -        | 优先 |
| 详情            | detail   | -        | 建议 |
| 亚马逊          | amazon   | -        | 可选 |
| 停售/停用/暂未售| discontinued | -   | 默认不索引 |

### 4. 识别共享图片
- 根文件夹下直接存放的图片（不归属于任何子文件夹），通常为包装图、多 SKU 共享图
- 标记为 shared_images

### 5. 提取规格
从文件夹名和可能的 CSV 信息中提取：
- 接口：PCIe 版本 + 设备接口（如 PCIe 4.0 x1 → M.2 NVMe）
- 尺寸：2230/2242/2260/2280/22110、线长（XXCM）
- 颜色：从名称中提取
- 版本/型号：从名称中提取

### 6. 生成唯一 ID
- product_id：优先用 13 位 69 码；无 69 码用自定义 SKU；否则用 group_id + 序号
- group_id：推荐格式 "品类缩写-后四位码"，如 "ADAPTER-2233-2240"

## 输出格式

输出严格 JSONL（每行一个产品组的完整 JSON 对象）：

```jsonl
{json.dumps(json.loads(PRODUCT_JSONL_SCHEMA.strip()), indent=2, ensure_ascii=False)}
```

## 待分析目录

NAS 根目录：{folder_path}

目录结构：
```
{folder_structure}
```

## 重要提醒
- 一个产品组一行 JSON，不要换行
- 69 码后四位从文件夹名中所有 4 位数字提取
- 中文和英语 image_set 标记 is_primary = true
- 优先使用中文名称作为产品名
- 如果没有发现多 SKU，products 数组只含一个元素
"""


# ═══════════════════════════════════════════════════════════════════
# 目录结构预扫描（生成 folder_structure 文本给 LLM）
# ═══════════════════════════════════════════════════════════════════
def scan_structure(root: str, max_depth: int = 3, max_items: int = 200) -> str:
    """
    扫描目录结构并生成缩进文本（供 LLM 分析）。
    只展示文件夹，不展示文件。
    """
    lines = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirnames.clear()
            continue

        prefix = "  " * depth + ("└── " if depth > 0 else "")
        folder_name = os.path.basename(dirpath) if depth > 0 else os.path.basename(root) or root
        # 统计图片数量
        img_count = sum(1 for f in filenames if f.lower().endswith(('.jpg','.jpeg','.png','.bmp','.webp')))
        img_hint = f" ({img_count} 张图)" if img_count else ""
        lines.append(f"{prefix}{folder_name}/{img_hint}")

        count += 1
        if count >= max_items:
            lines.append(f"... (截断，共 {max_items} 项)")
            break

        # 排序子目录
        dirnames.sort()

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="构建产品知识库 — 扫描 NAS 目录 + 生成 LLM 提示词"
    )
    parser.add_argument("--input", "-i", required=True, help="NAS 图片根目录路径")
    parser.add_argument("--output", "-o", default="products.jsonl", help="输出 JSONL 文件路径")
    parser.add_argument("--model", "-m", default="deepseek-v3", help="LLM 模型名")
    parser.add_argument("--prompt-only", "-p", action="store_true",
                        help="只生成提示词（不调用 LLM，手动复制给 AI）")
    parser.add_argument("--scan-only", "-s", action="store_true",
                        help="只扫描目录结构，不生成完整提示词")
    args = parser.parse_args()

    root = args.input
    if not os.path.isdir(root):
        print(f"错误：目录不存在 — {root}")
        sys.exit(1)

    # 扫描目录结构
    print(f"扫描目录：{root}")
    structure = scan_structure(root)
    print(f"目录结构：\n{structure}\n")

    if args.scan_only:
        return

    # 生成提示词
    prompt = build_prompt(root, structure)
    print("=" * 60)
    print("LLM 提示词（复制给 AI）：")
    print("=" * 60)
    print(prompt)
    print("=" * 60)

    if args.prompt_only:
        print(f"\n提示词已生成。请复制上面的提示词，连同目录结构一起发给 AI。")
        print(f"将 AI 返回的 JSONL 保存为 {args.output}")
        print(f"然后在主应用中：导入 → 导入知识库 → 选择 {args.output}")
        return

    print(f"\n提示：此工具目前只生成提示词。")
    print(f"如需自动调用 LLM API，请设置环境变量 DEEPSEEK_API_KEY 后使用 --auto 参数。")


if __name__ == "__main__":
    main()
