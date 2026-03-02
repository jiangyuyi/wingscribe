#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复数据库中带有日期前缀的地点名称及其 EXIF 信息

功能：
1. 扫描数据库中所有带有日期前缀的 location_tag
2. 清理日期前缀（如 "2026_北京东埠头沟公园" -> "北京东埠头沟公园"）
3. 更新数据库中的 location_tag
4. 更新对应裁切图的 EXIF 信息

用法：
    python scripts/fix_location_prefix.py
    python scripts/fix_location_prefix.py --dry-run  # 只显示不修改
    python scripts/fix_location_prefix.py --db-path "自定义路径/wingscribe.db"
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.metadata.exif_writer import ExifWriter


def parse_args():
    parser = argparse.ArgumentParser(description="修复数据库中带有日期前缀的地点名称")
    parser.add_argument("--db-path", default="data/db/wingscribe.db",
                        help="数据库文件路径 (默认: data/db/wingscribe.db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示要修改的内容，不实际执行修改")
    parser.add_argument("--base-dir", default=None,
                        help="基础目录路径，用于解析相对路径")
    return parser.parse_args()


def clean_location_tag(location_tag: str) -> str:
    """
    清理地点标签中的日期前缀

    示例:
        "2026_北京东埠头沟公园" -> "北京东埠头沟公园"
        "20260101-20260105北京" -> "北京"
        "2025_冬季北京" -> "冬季北京"
    """
    if not location_tag:
        return location_tag

    # 匹配 4-8 位数字开头的日期前缀
    date_pattern = re.compile(r'^(\d{4,8})[_,\-\s]+(.*)$')
    match = date_pattern.match(location_tag)

    if match:
        date_part = match.group(1)
        remaining = match.group(2)
        print(f"  清理: '{location_tag}' -> '{remaining}' (移除前缀: {date_part})")
        return remaining

    return location_tag


def update_exif_for_photo(photo: dict, base_dir: Path, dry_run: bool = False) -> bool:
    """
    更新单张照片的 EXIF 信息

    Args:
        photo: 照片记录字典
        base_dir: 基础目录
        dry_run: 是否只显示不修改

    Returns:
        是否成功
    """
    file_path = photo.get('file_path')
    if not file_path:
        return False

    # 解析文件路径
    if base_dir and not Path(file_path).is_absolute():
        full_path = base_dir / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        print(f"  警告: 文件不存在 - {full_path}")
        return False

    # 准备 EXIF 标签
    cn_name = photo.get('primary_bird_cn', '')
    sci_name = photo.get('scientific_name', '')
    location_tag = photo.get('location_tag', '')

    if not cn_name or not sci_name:
        return False

    description = f"{cn_name} ({sci_name})"

    # IPTC 关键词需要包含地点标签
    tags = {
        "ImageDescription": description,
        "XMP:Description": description,
        "XPTitle": description,
        "IPTC:Keywords": [cn_name, location_tag, sci_name, "WingScribe"]
    }

    if dry_run:
        print(f"  [DRY-RUN] 更新 EXIF: {full_path.name}")
        print(f"    Description: {description}")
        print(f"    Keywords: {tags['IPTC:Keywords']}")
        return True

    try:
        exif_writer = ExifWriter()
        result = exif_writer.write_metadata(str(full_path), tags)
        if result:
            print(f"  已更新 EXIF: {full_path.name}")
        return result
    except Exception as e:
        print(f"  错误: 更新 EXIF 失败 - {e}")
        return False


def main():
    args = parse_args()

    # 设置输出编码
    sys.stdout.reconfigure(encoding='utf-8')

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"错误: 数据库文件不存在 - {db_path}")
        sys.exit(1)

    print(f"连接到数据库: {db_path}")
    print()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 查询所有照片记录
    cursor = conn.execute('''
        SELECT id, file_path, filename, location_tag, primary_bird_cn, scientific_name
        FROM photos
        WHERE location_tag IS NOT NULL AND location_tag != ''
    ''')
    photos = cursor.fetchall()

    print(f"数据库中共有 {len(photos)} 条照片记录")
    print()

    # 日期前缀匹配模式
    date_pattern = re.compile(r'^(\d{4,8})[_,\-\s]')

    # 统计
    total_fixed = 0
    total_exif_updated = 0
    photos_to_fix = []

    for photo in photos:
        location_tag = photo['location_tag']
        match = date_pattern.match(location_tag)

        if match:
            new_location_tag = clean_location_tag(location_tag)
            if new_location_tag != location_tag:
                photos_to_fix.append({
                    'id': photo['id'],
                    'old_location': location_tag,
                    'new_location': new_location_tag,
                    'file_path': photo['file_path'],
                    'primary_bird_cn': photo['primary_bird_cn'],
                    'scientific_name': photo['scientific_name']
                })

    print(f"发现 {len(photos_to_fix)} 条记录需要修复")
    print()

    if not photos_to_fix:
        print("没有需要修复的记录")
        conn.close()
        return

    # 显示要修复的记录
    print("需要修复的记录:")
    for item in photos_to_fix:
        print(f"  ID {item['id']}: '{item['old_location']}' -> '{item['new_location']}'")
    print()

    if args.dry_run:
        print("[DRY-RUN 模式] 未执行实际修改")
        conn.close()
        return

    # 执行修复
    print("开始修复...")

    # 解析 base_dir
    base_dir = None
    if args.base_dir:
        base_dir = Path(args.base_dir)
    else:
        # 尝试从配置读取 base_dir
        try:
            from src.utils.config_loader import load_config
            config = load_config()
            base_dir = Path(config.get('paths', {}).get('base_dir', ''))
            if not base_dir:
                base_dir = None
        except Exception as e:
            print(f"警告: 无法读取配置中的 base_dir - {e}")
            base_dir = None

    if base_dir:
        print(f"使用 base_dir: {base_dir}")

    for item in photos_to_fix:
        # 更新数据库
        conn.execute(
            'UPDATE photos SET location_tag = ? WHERE id = ?',
            (item['new_location'], item['id'])
        )
        total_fixed += 1
        print(f"  已更新数据库 ID {item['id']}: {item['old_location']} -> {item['new_location']}")

        # 更新 EXIF
        if update_exif_for_photo(item, base_dir, dry_run=False):
            total_exif_updated += 1

    # 提交更改
    conn.commit()
    print()

    print(f"修复完成!")
    print(f"  - 更新数据库记录: {total_fixed}")
    print(f"  - 更新 EXIF 信息: {total_exif_updated}")

    conn.close()


if __name__ == '__main__':
    main()
