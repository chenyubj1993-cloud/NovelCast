#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试LLM分割功能（不生成TTS）
只处理前N个字符，快速验证分割逻辑
"""

import asyncio
import sys
import time
from pathlib import Path

from novelcast.log import log

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from novelcast.config_manager import get_config
from novelcast.dialogue_splitter import clear_global_character_map, get_global_character_map, split_dialogues_async
from novelcast.novel_reader import read_novel, split_chapters


async def test_split(file_path: str, max_chars: int = 3000):
    """
    测试LLM分割功能

    Args:
        file_path: 小说文件路径
        max_chars: 最大字符数
    """
    log.info("=" * 60)
    log.info("  LLM分割测试")
    log.info(f"  文件: {file_path}")
    log.info(f"  限制: 前{max_chars}字")
    log.info("=" * 60)

    # 加载配置
    get_config()

    # 读取小说
    log.info("\n📖 读取小说...")
    try:
        book_name, content = read_novel(file_path)
        log.info(f"  书名: {book_name}")
        log.info(f"  原始长度: {len(content)}字")
    except Exception as e:
        log.info(f"❌ 读取失败: {e}")
        return

    # 清空全局人物映射表
    clear_global_character_map()

    # 分割章节
    log.info("\n📑 分割章节...")
    chapters = split_chapters(content)
    log.info(f"  章节数: {len(chapters)}")

    # 限制字符数
    if max_chars > 0:
        total_chars = 0
        filtered_chapters = []
        for chapter in chapters:
            if total_chars + len(chapter.text) > max_chars:
                # 截断当前章节
                remaining = max_chars - total_chars
                if remaining > 0:
                    from novelcast.novel_reader import Chapter
                    filtered_chapter = Chapter(
                        number=chapter.number,
                        title=chapter.title,
                        text=chapter.text[:remaining]
                    )
                    filtered_chapters.append(filtered_chapter)
                    total_chars += remaining
                break
            filtered_chapters.append(chapter)
            total_chars += len(chapter.text)
        chapters = filtered_chapters
        log.info(f"  限制后: {len(chapters)}章, {total_chars}字")

    # 测试每个章节的分割
    log.info("\n" + "=" * 60)
    log.info("  开始LLM分割测试")
    log.info("=" * 60)

    start_time = time.time()
    total_lines = 0
    total_coverage = 0.0

    for i, chapter in enumerate(chapters, 1):
        log.info(f"\n{'─'*50}")
        log.info(f"📝 章节 {i}/{len(chapters)}: {chapter.title}")
        log.info(f"   文本长度: {len(chapter.text)}字")
        log.info(f"{'─'*50}")

        chapter_start = time.time()

        try:
            lines = await split_dialogues_async(chapter.text, chapter.title, book_name)
            chapter_elapsed = time.time() - chapter_start

            if not lines:
                log.info("   ❌ 返回空结果")
                continue

            # 计算覆盖率
            split_len = sum(len(line.text) for line in lines)
            coverage = split_len / len(chapter.text) if len(chapter.text) > 0 else 0

            log.info("\n   ✅ 分割完成:")
            log.info(f"      段落数: {len(lines)}")
            log.info(f"      覆盖率: {coverage:.1%}")
            log.info(f"      耗时: {chapter_elapsed:.1f}秒")

            # 统计角色
            characters = {}
            for line in lines:
                if line.character not in characters:
                    characters[line.character] = 0
                characters[line.character] += 1

            log.info("\n   🎭 角色统计:")
            for char, count in sorted(characters.items(), key=lambda x: -x[1]):
                log.info(f"      {char}: {count}段")

            # 显示前5段示例
            log.info("\n   📄 前5段示例:")
            for j, line in enumerate(lines[:5], 1):
                text_preview = line.text[:50] + "..." if len(line.text) > 50 else line.text
                log.info(f"      {j}. [{line.character}] {text_preview}")

            total_lines += len(lines)
            total_coverage += coverage

        except Exception as e:
            log.info(f"   ❌ 分割失败: {e}")
            import traceback
            traceback.print_exc()

    # 汇总
    elapsed = time.time() - start_time
    avg_coverage = total_coverage / len(chapters) if chapters else 0

    log.info("\n" + "=" * 60)
    log.info("  测试汇总")
    log.info("=" * 60)
    log.info(f"  章节数: {len(chapters)}")
    log.info(f"  总段落数: {total_lines}")
    log.info(f"  平均覆盖率: {avg_coverage:.1%}")
    log.info(f"  总耗时: {elapsed:.1f}秒")

    # 打印全局人物映射表
    character_map = get_global_character_map()
    if character_map:
        log.info("\n🎭 全局人物映射表:")
        for char, voice in character_map.items():
            log.info(f"   {char} -> {voice}")

    log.info("\n🎉 测试完成！")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        log.info("用法: python test_split.py <小说文件> [最大字符数]")
        log.info("示例: python test_split.py input/嫦娥.docx 3000")
        sys.exit(1)

    file_path = sys.argv[1]
    max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 3000

    asyncio.run(test_split(file_path, max_chars))
