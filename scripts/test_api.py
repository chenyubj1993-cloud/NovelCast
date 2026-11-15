#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API测试脚本
"""

import sys
from pathlib import Path

from novelcast.log import log

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from novelcast.config_manager import get_config
from novelcast.dialogue_splitter import get_llm_client
from novelcast.tts_generator import get_tts_client


def test_llm_sync():
    """测试LLM同步API"""
    log.info("\n🔍 测试LLM同步API...")
    config = get_config()

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=config.llm_api.model,
            messages=[{"role": "user", "content": "你好"}],
            max_tokens=10
        )

        log.info("✅ LLM同步API测试成功")
        log.info(f"   模型: {config.llm_api.model}")
        log.info(f"   响应: {response.choices[0].message.content}")

        return True

    except Exception as e:
        log.info(f"❌ LLM同步API测试失败: {e}")
        return False


def test_tts_sync():
    """测试TTS同步API"""
    log.info("\n🔍 测试TTS同步API...")
    config = get_config()

    try:
        client = get_tts_client()
        client.chat.completions.create(
            model=config.tts_api.model,
            messages=[
                {"role": "user", "content": "用平静的语气朗读"},
                {"role": "assistant", "content": "你好，这是一个测试。"}
            ],
            audio={"format": "wav", "voice": "冰糖"}
        )

        log.info("✅ TTS同步API测试成功")
        log.info(f"   模型: {config.tts_api.model}")

        return True

    except Exception as e:
        log.info(f"❌ TTS同步API测试失败: {e}")
        return False


def main():
    """主函数"""
    log.info("\n" + "="*60)
    log.info("  有声书生成器 - API测试")
    log.info("="*60)

    config = get_config()

    log.info("\n当前配置:")
    log.info("  LLM API:")
    log.info(f"    URL: {config.llm_api.base_url}")
    log.info(f"    密钥: {'*' * 8 if config.llm_api.api_key else '未设置'}")
    log.info(f"    模型: {config.llm_api.model}")
    log.info("  TTS API:")
    log.info(f"    URL: {config.tts_api.base_url}")
    log.info(f"    密钥: {'*' * 8 if config.tts_api.api_key else '未设置'}")
    log.info(f"    模型: {config.tts_api.model}")

    # 检查密钥
    if not config.llm_api.api_key and not config.tts_api.api_key:
        log.info("\n❌ 未设置任何API密钥，请先运行 configure.py 设置")
        return

    results = {}

    # 测试LLM API
    if config.llm_api.api_key:
        results["llm"] = test_llm_sync()
    else:
        log.info("\n⚠️ LLM API密钥未设置，跳过测试")
        results["llm"] = None

    # 测试TTS API
    if config.tts_api.api_key:
        results["tts"] = test_tts_sync()
    else:
        log.info("\n⚠️ TTS API密钥未设置，跳过测试")
        results["tts"] = None

    # 总结
    log.info("\n" + "="*60)
    log.info("  测试结果")
    log.info("="*60)

    if results["llm"] is not None:
        log.info(f"  LLM API: {'✅ 正常' if results['llm'] else '❌ 失败'}")
    else:
        log.info("  LLM API: ⏭ 跳过")

    if results["tts"] is not None:
        log.info(f"  TTS API: {'✅ 正常' if results['tts'] else '❌ 失败'}")
    else:
        log.info("  TTS API: ⏭ 跳过")

    # 判断是否可以开始生成
    can_generate = True
    if results["llm"] is False:
        can_generate = False
    if results["tts"] is False:
        can_generate = False

    if can_generate:
        log.info("\n🎉 测试通过！可以开始生成有声书了。")
    else:
        log.info("\n⚠️ 存在测试失败，请检查配置和网络连接。")


if __name__ == "__main__":
    main()
