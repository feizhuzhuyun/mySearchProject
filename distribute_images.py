"""
将 D:\壁纸 中的图片随机分发到 test_data/nas_root 下的各文件夹。
用于后续以图搜图测试。
"""
import os
import random
import shutil
import sys

SOURCE_DIR = r"D:\壁纸"
TARGET_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "nas_root")

def main():
    if not os.path.isdir(SOURCE_DIR):
        print(f"[ERROR] 源目录不存在: {SOURCE_DIR}")
        print("请确认 D:\\壁纸 文件夹存在且包含图片。")
        sys.exit(1)

    if not os.path.isdir(TARGET_ROOT):
        print(f"[ERROR] 目标根目录不存在: {TARGET_ROOT}")
        print("请先运行 prepare_test_data.py 创建测试目录。")
        sys.exit(1)

    # 收集源图片
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    source_files = []
    for fname in os.listdir(SOURCE_DIR):
        ext = os.path.splitext(fname)[1].lower()
        if ext in exts:
            source_files.append(os.path.join(SOURCE_DIR, fname))

    if not source_files:
        print(f"[WARN] D:\\壁纸 中没有图片文件。")
        return

    print(f"源图片: {len(source_files)} 张")

    # 收集目标文件夹（排除空文件夹和无码文件夹）
    target_folders = []
    for name in os.listdir(TARGET_ROOT):
        path = os.path.join(TARGET_ROOT, name)
        if os.path.isdir(path) and name != "EmptyFolder_5678":
            # 检查是否有已有的图片文件
            has_files = any(
                os.path.splitext(f)[1].lower() in exts
                for f in os.listdir(path)
            ) if os.path.exists(path) else False
            if has_files:
                target_folders.append(path)

    if not target_folders:
        print("[ERROR] 目标目录中没有包含图片的子文件夹。")
        sys.exit(1)

    print(f"目标文件夹: {len(target_folders)} 个")

    # 随机分发
    random.shuffle(source_files)
    per_folder = max(1, len(source_files) // len(target_folders))

    counts = {}
    for i, src in enumerate(source_files):
        folder = target_folders[i % len(target_folders)]
        dst = os.path.join(folder, os.path.basename(src))
        shutil.copy2(src, dst)
        counts[folder] = counts.get(folder, 0) + 1

    print(f"\n分发完成:")
    for folder, count in sorted(counts.items(),
                                 key=lambda x: x[1], reverse=True):
        name = os.path.basename(folder)
        print(f"  [{count:3d}] {name}")

    total = sum(counts.values())
    print(f"\n共分发 {total} 张图片到 {len(counts)} 个文件夹。")
    print("提示：分发后需要点 [重建索引] 更新数据库，才能在搜索中看到新图片。")

if __name__ == "__main__":
    main()
