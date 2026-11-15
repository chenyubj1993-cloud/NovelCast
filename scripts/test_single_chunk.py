#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试单个chunk的LLM分割功能
"""

import asyncio
import sys
import time
from pathlib import Path

from novelcast.log import log

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from novelcast.config_manager import get_config
from novelcast.dialogue_splitter import _recursive_split_by_moderation_async, get_async_llm_client
from novelcast.novel_reader import read_novel


async def test_single_chunk():
    """测试单个chunk的分割"""
    log.info("=" * 60, flush=True)
    log.info("  单个Chunk分割测试", flush=True)
    log.info("=" * 60, flush=True)

    # 加载配置
    log.info("正在加载配置...", flush=True)
    config = get_config()
    log.info(f"配置加载完成: {config.llm_api.model}", flush=True)

    # 读取小说
    log.info("\n📖 读取小说...", flush=True)
    try:
        book_name, content = read_novel("input/嫦娥.docx")
        log.info(f"  书名: {book_name}", flush=True)
        log.info(f"  原始长度: {len(content)}字", flush=True)
    except Exception as e:
        log.info(f"❌ 读取失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return

    # 取前1000字测试
    test_text = content[:1000]
    log.info("\n📝 测试文本:", flush=True)
    log.info(f"  长度: {len(test_text)}字", flush=True)
    log.info(f"  前100字: {test_text[:100]}...", flush=True)

    # 创建客户端
    log.info("\n🔧 创建API客户端...", flush=True)
    client = get_async_llm_client()
    log.info(f"  模型: {config.llm_api.model}", flush=True)
    log.info(f"  Base URL: {config.llm_api.base_url}", flush=True)

    # 测试分割
    log.info("\n🚀 开始分割测试...", flush=True)
    start_time = time.time()

    try:
        log.info("  调用_recursive_split_by_moderation_async...", flush=True)
        lines = await _recursive_split_by_moderation_async(
            client, test_text, "测试章节", "test_chunk", book_name
        )
        elapsed = time.time() - start_time

        log.info("\n✅ 分割完成:", flush=True)
        log.info(f"  段落数: {len(lines)}", flush=True)
        log.info(f"  耗时: {elapsed:.1f}秒", flush=True)

        # 计算覆盖率
        split_len = sum(len(line.text) for line in lines)
        coverage = split_len / len(test_text) if len(test_text) > 0 else 0
        log.info(f"  覆盖率: {coverage:.1%}")

        # 统计角色
        characters = {}
        for line in lines:
            if line.character not in characters:
                characters[line.character] = 0
            characters[line.character] += 1

        log.info("\n🎭 角色统计:")
        for char, count in sorted(characters.items(), key=lambda x: -x[1]):
            log.info(f"    {char}: {count}段")

        # 显示所有段落
        log.info("\n📄 所有段落:")
        for j, line in enumerate(lines, 1):
            text_preview = line.text[:80] + "..." if len(line.text) > 80 else line.text
            log.info(f"  {j}. [{line.character}] {text_preview}")

    except Exception as e:
        elapsed = time.time() - start_time
        log.info(f"\n❌ 分割失败: {e}", flush=True)
        log.info(f"  耗时: {elapsed:.1f}秒", flush=True)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(test_single_chunk())
    except KeyboardInterrupt:
        log.info("\n⚠️ 用户中断")
    except Exception as e:
        log.info(f"\n❌ 未捕获的异常: {e}")
        import traceback
        traceback.print_exc()
