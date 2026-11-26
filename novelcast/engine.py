#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
有声书生成主脚本

两阶段执行：
  阶段1: LLM分割所有章节 → 验证全部成功
  阶段2: TTS生成音频 → 合并输出
"""

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from novelcast.log import log

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from novelcast.cast_manager import apply_cast, build_cast, load_cast, print_cast, save_cast
from novelcast.character_registry import (
    build_roster_async,
    load_roster,
    names_from_prompt_map,
    roster_to_prompt_map,
    save_roster,
)
from novelcast.config_manager import ConfigManager, get_config
from novelcast.coverage_analyzer import analyze_coverage, print_coverage_report, print_summary
from novelcast.dialogue_splitter import (
    DialogueLine,
    clear_global_character_map,
    get_async_llm_client,
    split_dialogues_async,
)
from novelcast.llm_review import review_unknown
from novelcast.novel_reader import Chapter, read_novel, split_chapters
from novelcast.script_qa import (
    alignment,
    dedupe_adjacent,
    format_gap,
    repair_attributions,
    repair_narration,
    repair_tail,
)
from novelcast.utils import format_duration, get_wav_duration, safe_filename


@dataclass
class ChapterSplitResult:
    """章节分割结果"""
    chapter: Chapter
    lines: List[DialogueLine]
    coverage: float
    success: bool
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="有声书生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generate.py novel.txt                    # 使用默认配置生成
  python generate.py novel.txt -c 3               # 只处理前3章
  python generate.py novel.txt --first-paragraphs 10  # 只处理每个章节的前10段
  python generate.py novel.txt --first-chars 5000     # 只处理每个章节的前5000字
  python generate.py novel.txt --no-skip           # 不跳过已生成的章节
  python generate.py novel.txt --chunk-size 2000   # 设置LLM分割的chunk大小
        """
    )

    parser.add_argument("novel", help="小说文件路径（支持 input/ 下相对路径）")
    parser.add_argument("-o", "--output", help="输出目录（默认 output/{书名}_有声书）")
    parser.add_argument("-c", "--chapters", type=int, default=0, help="处理章节数（0=全部）")
    parser.add_argument("--first-paragraphs", type=int, help="只处理每个章节的前N段")
    parser.add_argument("--first-chars", type=int, help="只处理每个章节的前N个字符")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已生成的章节")
    parser.add_argument("--chunk-size", type=int, help="LLM分割的chunk大小（字符数）")
    parser.add_argument("--max-duration", type=int, help="单个音频文件最大时长（秒）")
    parser.add_argument("--split-only", action="store_true", help="只执行LLM分割，不生成音频")
    parser.add_argument("--test", action="store_true", help="测试API连接")
    parser.add_argument("--min-split-length", type=int, help="最小分割长度（字符数），低于此长度的文本将被跳过")
    parser.add_argument("--fresh", action="store_true", help="清空输出目录、缓存和角色表，从头生成")
    parser.add_argument("--restart", action="store_true", help="保留剧本，但丢弃分段缓存、重新合成音频")
    parser.add_argument("--keep-segments", action="store_true", help="合成后保留分段缓存（默认整章成功后清理，省磁盘）")
    parser.add_argument("--rebuild-roster", action="store_true", help="忽略已有 characters.json，重新抽取角色表")
    parser.add_argument("--rebuild-cast", action="store_true", help="忽略已有 cast.json，按当前角色表/音色库重新分配音色")
    parser.add_argument("--offline", action="store_true", help="离线模式：只读取已有剧本，不调用 LLM（角色表取自 characters.json 或剧本）")

    return parser.parse_args()


# ============================================================
# 阶段1: LLM分割
# ============================================================

async def split_chapter(
    chapter: Chapter,
    book_name: str,
    config: ConfigManager,
    character_map: Optional[Dict[str, str]] = None
) -> ChapterSplitResult:
    """
    分割单个章节（LLM调用）

    Args:
        chapter: 章节数据
        book_name: 书名
        config: 配置管理器

    Returns:
        章节分割结果
    """
    start_time = time.time()
    start_str = time.strftime("%H:%M:%S.") + f"{start_time % 1:.3f}"[2:]  # 毫秒级
    log.info(f"  📝 [{start_str}] 章节 {chapter.number:03d}: {chapter.title} ({len(chapter.text)}字) 开始处理")

    try:
        lines = await split_dialogues_async(chapter.text, chapter.title, book_name, character_map=character_map)

        if not lines:
            return ChapterSplitResult(
                chapter=chapter,
                lines=[],
                coverage=0.0,
                success=False,
                error="LLM返回空结果",
                start_time=start_time,
                end_time=time.time()
            )

        # 先去掉 LLM 连续重复输出的同一句，再做逐字对齐
        lines, dup_removed = dedupe_adjacent(lines)
        if dup_removed:
            log.info(f"  🧹 去重: 删除连续重复 {dup_removed} 行")

        # 逐字对齐：定位丢字；结尾被整段截断的补成旁白
        report = alignment(chapter.text, lines)
        if report["gaps"]:
            tail_added = repair_tail(chapter.text, lines)
            attr_added = repair_attributions(chapter.text, lines)
            nar_added = repair_narration(chapter.text, lines)
            if tail_added or attr_added or nar_added:
                log.info(f"  🩹 修复: 补结尾 {tail_added} 字、补回 {attr_added} 处「XX说/问」、{nar_added} 处短旁白")
                report = alignment(chapter.text, lines)
        if report["gaps"] or report["extra_chars"]:
            log.info(
                f"  🔍 对齐检查: 内容覆盖 {report['content_coverage']:.2%}，"
                f"缺失 {report['missing_chars']} 字 / {report['missing_spans']} 处，"
                f"多出 {report['extra_chars']} 字 / {report['extra_spans']} 处"
                f"（另有 {report['punctuation_chars']} 个标点被合并，不影响朗读）"
            )
            for gap in report["gaps"][:3]:
                log.info(f"     缺字 {format_gap(gap)}")

        # 默认用 LLM 复核「未知」说话人：只改 character，不动文字
        if character_map and config.config.get("review_unknown", True):
            unknown_idx = [i for i, line in enumerate(lines) if line.character == "未知"]
            if unknown_idx:
                try:
                    payload = [{"character": line.character, "text": line.text} for line in lines]
                    payload, changes = await asyncio.to_thread(
                        review_unknown,
                        payload,
                        {name: {} for name in names_from_prompt_map(character_map)},
                        config,
                    )
                    for idx, _old, new in changes:
                        lines[idx].character = new
                    if changes:
                        log.info(f"  🤖 LLM 复核修正 {len(changes)} 处「未知」说话人")
                except Exception as exc:  # noqa: BLE001
                    log.info(f"  ⚠️ LLM 复核跳过: {exc}")

        # 覆盖率按“实际文字”算：引号等标点在剧本里本来就会被合并
        original_len = len(chapter.text)
        coverage = report["content_coverage"] if original_len > 0 else 0

        elapsed = time.time() - start_time
        end_str = time.strftime("%H:%M:%S.") + f"{time.time() % 1:.3f}"[2:]  # 毫秒级
        # 覆盖率过低说明 LLM 大面积漏字，这种剧本不能算成功（否则音频会被 skip_existing 锁死）
        min_coverage = float(config.config.get("min_coverage", 0.7) or 0.7)
        if coverage < min_coverage:
            log.info(
                f"  ❌ [{end_str}] 章节 {chapter.number:03d} 覆盖率仅 {coverage:.1%}"
                f"（阈值 {min_coverage:.0%}），判定失败"
            )
            return ChapterSplitResult(
                chapter=chapter,
                lines=lines,
                coverage=coverage,
                success=False,
                start_time=start_time,
                end_time=time.time(),
            )
        log.info(f"  ✅ [{end_str}] 章节 {chapter.number:03d} 分割完成: {len(lines)}段, 覆盖率{coverage:.1%} (耗时{elapsed:.1f}秒)")

        return ChapterSplitResult(
            chapter=chapter,
            lines=lines,
            coverage=coverage,
            success=True,
            start_time=start_time,
            end_time=time.time()
        )

    except Exception as e:
        log.info(f"    ❌ 分割失败: {e}")
        return ChapterSplitResult(
            chapter=chapter,
            lines=[],
            coverage=0.0,
            success=False,
            error=str(e),
            start_time=start_time,
            end_time=time.time()
        )


def _load_script_result(chapter: Chapter, book_name: str, config: ConfigManager) -> Optional[ChapterSplitResult]:
    """断点续跑：如果本章剧本已存在，直接复用，不再调用 LLM。"""
    script_file = config.get_output_dir(book_name) / f"{chapter.number:03d}_{safe_filename(chapter.title)}_script.json"
    if not script_file.exists():
        return None
    try:
        data = json.loads(script_file.read_text(encoding="utf-8"))
        lines = [
            DialogueLine(
                character=item.get("character", "旁白"),
                text=item.get("text", ""),
                emotion=item.get("emotion", "neutral"),
                voice_id=item.get("voice", ""),
            )
            for item in data.get("lines", [])
            if item.get("text")
        ]
    except Exception as exc:  # noqa: BLE001
        log.info(f"    ⚠️ 读取已有剧本失败（{exc}），重新分割")
        return None
    if not lines:
        return None
    # 半章剧本（--first-chars / --first-paragraphs）或旧版残缺剧本不能当整章成品复用
    if data.get("partial") and not getattr(chapter, "partial", False):
        log.info("    ⚠️ 已有剧本是「前若干字」的试跑结果（partial=true），重新分割")
        return None
    recorded = data.get("source_chars")
    if recorded and abs(int(recorded) - len(chapter.text)) > max(50, int(0.02 * len(chapter.text))):
        log.info(f"    ⚠️ 已有剧本对应 {recorded} 字，本章 {len(chapter.text)} 字（源文本变了），重新分割")
        return None
    report = alignment(chapter.text, lines)
    if report["content_coverage"] < 0.98:
        log.info(
            f"    ⚠️ 已有剧本只覆盖本章 {report['content_coverage']:.1%}"
            f"（{len(chapter.text)} 字 vs 剧本 {report['output_chars']} 字），重新分割"
        )
        return None
    original_len = len(chapter.text) or 1
    coverage = min(1.0, sum(len(line.text) for line in lines) / original_len)
    return ChapterSplitResult(
        chapter=chapter, lines=lines, coverage=coverage, success=True,
        start_time=time.time(), end_time=time.time()
    )


def _save_script_result(result: ChapterSplitResult, book_name: str, config: ConfigManager) -> Path:
    """把本章标注结果落盘为 {num:03d}_{title}_script.json，供断点续跑与 --offline 复用。"""
    output_dir = config.get_output_dir(book_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_file = output_dir / f"{result.chapter.number:03d}_{safe_filename(result.chapter.title)}_script.json"
    payload = {
        "chapter": {"number": result.chapter.number, "title": result.chapter.title},
        "coverage": round(result.coverage, 4),
        "partial": bool(getattr(result.chapter, "partial", False)),
        "source_chars": len(result.chapter.text or ""),
        "lines": [
            {
                "character": line.character,
                "text": line.text,
                "emotion": line.emotion,
                "voice": line.voice_id,
            }
            for line in result.lines
        ],
    }
    script_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return script_file


def _roster_from_scripts(output_dir: Path) -> dict:
    """离线模式：从已有 *_script.json 统计角色，生成最小角色表。"""
    from collections import Counter

    counts: Counter = Counter()
    for script in sorted(output_dir.glob("*_script.json")):
        try:
            data = json.loads(script.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for item in data.get("lines", []):
            name = (item.get("character") or "").strip()
            if name:
                counts[name] += 1

    characters = {}
    for idx, (name, appearances) in enumerate(counts.most_common()):
        characters[name] = {
            "name": name,
            "aliases": [],
            "gender": "unknown",
            "age": "unknown",
            "role": "protagonist" if idx == 0 else "minor",
            "description": "",
            "appearances": appearances,
        }
    return {
        "version": 1,
        "book": "",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "characters": characters,
    }


async def split_all_chapters(
    chapters: List[Chapter],
    book_name: str,
    config: ConfigManager,
    character_map: Optional[Dict[str, str]] = None,
    resume: bool = True,
    offline: bool = False
) -> Tuple[List[ChapterSplitResult], List[ChapterSplitResult]]:
    """
    阶段1: 分割所有章节

    Args:
        chapters: 章节列表
        book_name: 书名
        config: 配置管理器

    Returns:
        (成功结果列表, 失败结果列表)
    """
    log.info(f"\n{'='*60}")
    log.info("  阶段1: LLM分割所有章节")
    log.info(f"{'='*60}")

    start_time = time.time()
    results = []

    # 章节串行处理，块级并行在 split_dialogues_async 内部
    for chapter in chapters:
        cached = _load_script_result(chapter, book_name, config) if resume else None
        if cached is not None:
            log.info(f"  ⏭ 章节 {chapter.number:03d}: {chapter.title} 已有剧本，直接复用（{len(cached.lines)}段）")
            results.append(cached)
            continue
        if offline:
            log.info(f"  ⏭ 离线模式：章节 {chapter.number:03d} 没有可用剧本，跳过")
            results.append(ChapterSplitResult(
                chapter=chapter, lines=[], coverage=0.0, success=False,
                error="离线模式：缺少剧本",
            ))
            continue
        result = await split_chapter(chapter, book_name, config, character_map)
        if result.success:
            script_file = _save_script_result(result, book_name, config)
            log.info(f"    💾 剧本已保存: {script_file.name}")
        results.append(result)

    elapsed = time.time() - start_time

    # 分类结果
    success_results = [r for r in results if r.success]
    failed_results = [r for r in results if not r.success]

    log.info("\n  📊 分割统计:")
    log.info(f"     成功: {len(success_results)}/{len(chapters)} 章")
    log.info(f"     失败: {len(failed_results)}/{len(chapters)} 章")
    log.info(f"     耗时: {elapsed:.1f}秒")

    if failed_results:
        log.info("\n  ⚠️ 失败章节:")
        for r in failed_results:
            log.info(f"     - {r.chapter.title}: {r.error}")

    return success_results, failed_results


# ============================================================
# 阶段2: TTS生成
# ============================================================

async def generate_chapter_audio(
    result: ChapterSplitResult,
    book_name: str,
    config: ConfigManager,
    cast: Optional[dict] = None,
    skip_existing: bool = True,
    restart: bool = False,
    keep_segments: bool = False
) -> Optional[List[str]]:
    """
    生成单个章节的音频

    Args:
        result: 章节分割结果
        book_name: 书名
        config: 配置管理器
        skip_existing: 是否跳过已生成的章节

    Returns:
        生成的音频文件路径列表，失败返回None
    """
    chapter = result.chapter
    lines = result.lines

    log.info(f"\n  🎤 章节 {chapter.number:03d}: {chapter.title}")

    # 检查是否已存在（只认能读出时长的完整 wav，半截文件要重做）
    output_dir = config.get_output_dir(book_name)
    existing_files = [
        f for f in output_dir.glob(f"{chapter.number:03d}_*.wav")
        if get_wav_duration(str(f)) > 1.0
    ]

    if skip_existing and existing_files:
        log.info(f"    ⏭ 已存在（{len(existing_files)}个文件），跳过")
        return [str(f) for f in existing_files]

    # 分配音色：优先使用全书统一的 cast.json
    if cast:
        unknown = apply_cast(lines, cast)
        if unknown:
            log.info(f"    ⚠️ 角色表外角色（暂用旁白音色）: {', '.join(unknown[:8])}")
    else:
        default_voice = config.config.get("voice_presets", {}).get("default", "冰糖")
        for line in lines:
            line.voice_id = line.voice_id or default_voice

    # 本地/云端逐行 TTS（IndexTTS-2 / edge-tts / OpenAI 兼容云端）：逐行合成后直接拼成整章
    provider_name = config.config.get("tts", {}).get("provider", "edge")
    if provider_name in ("indextts2", "edge", "openai", "cloud"):
        from novelcast.local_tts import concat_segments, synthesize_lines

        label = "云端 TTS" if provider_name in ("openai", "cloud") else "本地 TTS"
        log.info(f"    🎧 {label}（{provider_name}），逐行合成中…")
        temp_dir = config.get_temp_dir(book_name, chapter.number)
        tts_cfg = config.config.get("tts", {})
        units = []
        done = synthesize_lines(
            [{"character": l.character, "text": l.text, "emotion": l.emotion} for l in lines],
            str(temp_dir),
            cast=cast,
            config=config,
            verbose=True,
            restart=restart,
            units_out=units,
        )
        segment_files = [done[i] for i in sorted(done)]
        characters = [units[i]["character"] for i in sorted(done)] if units else None
        log.info(f"    ✅ 本地合成 {len(segment_files)}/{len(lines)} 段")
        if not segment_files:
            log.info("    ❌ 没有生成任何音频")
            return None
        output_path = str(output_dir / f"{chapter.number:03d}_{safe_filename(chapter.title)}.wav")
        stats = {}
        concat_segments(
            segment_files,
            output_path,
            characters=characters,
            target_lufs=float(tts_cfg.get("loudness_lufs", -18.0)),
            silence_narration=float(tts_cfg.get("silence_narration", 0.4)),
            silence_dialogue=float(tts_cfg.get("silence_dialogue", 0.15)),
            stats=stats,
        )
        duration = stats.get("duration") or get_wav_duration(output_path)
        total_chars = sum(len(l.text) for l in lines)
        rate = total_chars / duration * 60 if duration else 0
        log.info(f"      ✅ {Path(output_path).name} ({format_duration(duration)})")
        log.info(
            f"      📊 自检: {rate:.0f} 字/分 · 最长段 {stats.get('max_segment', 0):.1f}s"
            f" · {stats.get('lufs', 0):.1f} LUFS · 峰值 {stats.get('peak', 0):.2f}"
        )
        issues = []
        if not 220 <= rate <= 340:
            issues.append(f"语速异常（{rate:.0f} 字/分）")
        if stats.get("max_segment", 0) > 30:
            issues.append(f"有超长分段（{stats['max_segment']:.0f}s）")
        if issues:
            log.info("      ⚠️ " + "；".join(issues) + "，建议抽听")

        script_file = output_dir / f"{chapter.number:03d}_{safe_filename(chapter.title)}_script.json"
        previous = {}
        if script_file.exists():
            try:
                previous = json.loads(script_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                previous = {}
        joined = "".join(l.text for l in lines)
        script_data = {
            "chapter": previous.get("chapter") or {"number": chapter.number, "title": chapter.title},
            "coverage": previous.get("coverage", round(len(joined) / max(1, len(chapter.text or "")), 4)),
            "partial": previous.get("partial", bool(getattr(chapter, "partial", False))),
            "source_chars": previous.get("source_chars", len(chapter.text or "")),
            "lines": [
                {"character": l.character, "text": l.text, "emotion": l.emotion, "voice": l.voice_id}
                for l in lines
            ],
        }
        try:
            with open(script_file, "w", encoding="utf-8") as f:
                json.dump(script_data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            log.error(f"      ❌ 剧本写盘失败：{exc}")
        _generate_readable_text_file(script_data, output_dir / f"{chapter.number:03d}_{safe_filename(chapter.title)}_readable.txt")

        # 整章成功落盘后再清分段缓存，避免中途失败丢掉可续跑进度
        if not keep_segments:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.info(f"      🧹 已清理分段缓存（{temp_dir.name}）")
        return [output_path]

    raise ValueError(
        f"不支持的 TTS provider: {provider_name}（可选：edge / indextts2 / openai）"
    )
    return None


def _generate_readable_text_file(script_data: dict, output_path: Path):
    """
    生成可读性强的文本文件

    Args:
        script_data: 脚本数据（包含chapter和lines）
        output_path: 输出文件路径
    """
    lines = []
    lines.append(f"=== {script_data['chapter']} ===")
    lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"共 {len(script_data['lines'])} 段")
    lines.append("")

    # 统计角色
    characters = set()
    for line in script_data['lines']:
        characters.add(line['character'])

    lines.append(f"角色列表: {', '.join(sorted(characters))}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("")

    # 逐段输出
    for i, line in enumerate(script_data['lines'], 1):
        character = line['character']
        text = line['text']
        emotion = line['emotion']
        voice = line['voice']

        # 格式化输出
        lines.append(f"{i:3d}. [{character}] ({voice})")
        lines.append(f"     {text}")
        if emotion != 'neutral':
            lines.append(f"     情绪: {emotion}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("=== 结束 ===")

    # 写入文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        log.info(f"      📄 可读文本: {output_path.name}")
    except Exception as e:
        log.info(f"      ⚠️ 生成可读文本失败: {e}")


async def generate_all_audio(
    success_results: List[ChapterSplitResult],
    book_name: str,
    config: ConfigManager,
    cast: Optional[dict] = None,
    skip_existing: bool = True,
    restart: bool = False,
    keep_segments: bool = False
) -> List[str]:
    """
    阶段2: 生成所有章节的音频

    Args:
        success_results: 成功的分割结果列表
        book_name: 书名
        config: 配置管理器
        skip_existing: 是否跳过已生成的章节

    Returns:
        生成的音频文件路径列表
    """
    log.info(f"\n{'='*60}")
    log.info("  阶段2: 生成音频")
    log.info(f"{'='*60}")

    start_time = time.time()
    all_output_files = []

    # 逐章生成音频
    for result in success_results:
        output_files = await generate_chapter_audio(result, book_name, config, cast, skip_existing, restart, keep_segments)
        if output_files:
            all_output_files.extend(output_files)

    elapsed = time.time() - start_time

    log.info("\n  📊 音频统计:")
    log.info(f"     生成文件: {len(all_output_files)} 个")
    log.info(f"     耗时: {elapsed:.1f}秒")

    return all_output_files


# ============================================================
# 内容过滤
# ============================================================

def _filter_chapters_content(
    chapters: List[Chapter],
    first_paragraphs: Optional[int] = None,
    first_chars: Optional[int] = None
) -> List[Chapter]:
    """
    过滤章节内容，只保留前N段或前N个字符

    Args:
        chapters: 章节列表
        first_paragraphs: 只保留前N段
        first_chars: 只保留前N个字符

    Returns:
        过滤后的章节列表
    """
    filtered_chapters = []

    for chapter in chapters:
        # 按段落分割
        paragraphs = chapter.text.split('\n\n')
        original_paragraph_count = len(paragraphs)

        # 应用段落数限制
        if first_paragraphs and first_paragraphs > 0:
            paragraphs = paragraphs[:first_paragraphs]

        # 应用字符数限制
        if first_chars and first_chars > 0:
            filtered_text = []
            current_chars = 0
            for para in paragraphs:
                if current_chars + len(para) > first_chars:
                    # 如果加上这段会超限，只取部分
                    remaining = first_chars - current_chars
                    if remaining > 0:
                        filtered_text.append(para[:remaining])
                    break
                filtered_text.append(para)
                current_chars += len(para)
            paragraphs = filtered_text

        # 重新组合文本
        filtered_text = '\n\n'.join(paragraphs)

        # 创建新的Chapter对象
        filtered_chapter = Chapter(
            number=chapter.number,
            title=chapter.title,
            text=filtered_text
        )
        # 标记「只取了一部分」：这种剧本不能当作整章成品复用
        filtered_chapter.partial = bool(len(filtered_text) < len(chapter.text))
        filtered_chapters.append(filtered_chapter)

        # 打印过滤信息
        if first_paragraphs or first_chars:
            log.info(f"  📝 章节 {chapter.number:03d}: {chapter.title}")
            if first_paragraphs:
                log.info(f"     段落: {original_paragraph_count} → {len(paragraphs)}")
            if first_chars:
                log.info(f"     字符: {len(chapter.text)} → {len(filtered_text)}")

    return filtered_chapters


# ============================================================
# 主函数
# ============================================================

async def main():
    """主函数"""
    from novelcast.log import setup as _setup_logging

    _setup_logging()
    args = parse_args()

    # 加载配置
    config = get_config()

    # 应用命令行参数
    if args.chunk_size:
        config.set("generation.chunk_size", args.chunk_size)
    if args.max_duration:
        config.set("generation.max_duration_per_file", args.max_duration)
    if args.min_split_length:
        config.set("generation.min_split_length", args.min_split_length)

    # 测试API连接
    if args.test:
        log.info("🔍 测试API连接...")

        # 测试LLM API
        log.info("\n📝 测试LLM API...")
        try:
            from novelcast.dialogue_splitter import get_llm_client
            llm_client = get_llm_client()
            llm_client.chat.completions.create(
                model=config.llm_api.model,
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=10
            )
            log.info(f"  ✅ LLM API连接成功 (模型: {config.llm_api.model})")
        except Exception as e:
            log.info(f"  ❌ LLM API连接失败: {e}")

        # mimoai 云端 TTS 已移除，TTS 连通性请用 `novelcast doctor` 检查

        return

    # 读取小说
    log.info("\n📖 读取小说...")
    try:
        book_name, content = read_novel(args.novel)
    except Exception as e:
        log.info(f"❌ 读取小说失败: {e}")
        return

    # 清空全局人物映射表（开始新书时重置）
    clear_global_character_map()
    log.info("  🔄 已清空全局人物映射表")

    # 输出目录：默认保留，支持断点续跑；--fresh 才清空
    output_dir = config.get_output_dir(book_name)
    if args.fresh:
        if output_dir.exists():
            shutil.rmtree(output_dir)
            log.info(f"  🗑️ 已清空输出目录: {output_dir}")
        from novelcast.dialogue_splitter import get_llm_cache
        removed = get_llm_cache(book_name).clear()
        log.info(f"  🗑️ 已清空 LLM 缓存: {removed} 个文件")
        llm_raw_dir = config.get_llm_raw_dir(book_name)
        if llm_raw_dir.exists():
            shutil.rmtree(llm_raw_dir)
            log.info(f"  🗑️ 已清空LLM原始响应目录: {llm_raw_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 分割章节
    log.info("\n📑 分割章节...")
    chapters = split_chapters(content)

    # 限制章节数
    if args.chapters > 0:
        chapters = chapters[:args.chapters]
        log.info(f"  限制处理前 {args.chapters} 章")

    # 部分处理选项：限制每个章节的段落数或字符数
    if args.first_paragraphs or args.first_chars:
        chapters = _filter_chapters_content(chapters, args.first_paragraphs, args.first_chars)

    # ============================================================
    # 交互式选择：让用户选择要处理的章节
    # ============================================================
    from novelcast.dialogue_splitter import _split_text_chunks

    log.info("\n📋 章节列表:")
    for i, chapter in enumerate(chapters, 1):
        log.info(f"  {i}. {chapter.title} ({len(chapter.text)}字)")

    if len(chapters) == 1 and chapters[0].title == "全文":
        # 没有章节标题，让用户输入块数
        chunk_size = config.generation.chunk_size
        all_chunks = _split_text_chunks(chapters[0].text, chunk_size)
        log.info("\n  检测到没有章节标题")
        log.info(f"  按{chunk_size}字分块，共{len(all_chunks)}块")
        log.info("  请输入要处理的块数（例如：2，直接回车处理全部）:")

        user_input = input("  > ").strip()
        if user_input:
            try:
                num_chunks = int(user_input)
                if num_chunks < 1:
                    log.info("❌ 块数必须大于0")
                    return
                # 取前N块
                selected_chunks = all_chunks[:num_chunks]
                log.info(f"\n  ✅ 选择处理前{num_chunks}块")
                for i, chunk in enumerate(selected_chunks, 1):
                    log.info(f"    块{i}: {len(chunk)}字")
            except ValueError:
                log.info("❌ 请输入有效的数字")
                return
        else:
            selected_chunks = all_chunks
            log.info(f"\n  ✅ 处理全部{len(selected_chunks)}块")

        # 每块作为独立章节处理
        from novelcast.novel_reader import Chapter
        chapters = []
        for i, chunk in enumerate(selected_chunks, 1):
            chapters.append(Chapter(
                number=i,
                title=f"块{i}",
                text=chunk
            ))
    else:
        # 有章节，让用户选择章节
        log.info(f"\n  检测到{len(chapters)}个章节")
        log.info("  请输入要处理的章节号（例如：2,3,4,6，直接回车处理全部）:")

        user_input = input("  > ").strip()
        if user_input:
            try:
                chapter_indices = [int(x.strip()) for x in user_input.split(",")]
                # 验证章节号
                for idx in chapter_indices:
                    if idx < 1 or idx > len(chapters):
                        log.info(f"❌ 章节号 {idx} 无效，有效范围: 1-{len(chapters)}")
                        return
                # 筛选章节
                chapters = [chapters[i-1] for i in chapter_indices]
                log.info(f"\n  ✅ 选择处理{len(chapters)}个章节")
                for i, chapter in enumerate(chapters, 1):
                    log.info(f"    {i}. {chapter.title} ({len(chapter.text)}字)")
            except ValueError:
                log.info("❌ 请输入有效的章节号（用逗号分隔）")
                return
        else:
            log.info(f"\n  ✅ 处理全部{len(chapters)}个章节")

    # ============================================================
    # 阶段0: 全书角色表（后续标注的枚举约束）
    # ============================================================
    roster_file = output_dir / "characters.json"
    roster = None if args.rebuild_roster else load_roster(roster_file)
    if roster:
        log.info(f"\n🎭 复用角色表: {len(roster['characters'])} 个角色（{roster_file.name}）")
    elif args.offline:
        log.info(f"\n{'='*60}")
        log.info("  阶段0: 离线模式，从已有剧本汇总角色")
        log.info(f"{'='*60}")
        roster = _roster_from_scripts(output_dir)
        save_roster(roster, roster_file)
        log.info(f"  💾 角色表已保存: {roster_file}（{len(roster['characters'])} 个角色）")
    else:
        log.info(f"\n{'='*60}")
        log.info("  阶段0: 全书角色抽取")
        log.info(f"{'='*60}")
        client = get_async_llm_client()
        roster = await build_roster_async(chapters, book_name, client, config)
        save_roster(roster, roster_file)
        log.info(f"  💾 角色表已保存: {roster_file}")
    character_map = roster_to_prompt_map(roster)

    # ============================================================
    # 阶段1: LLM分割
    # ============================================================
    success_results, failed_results = await split_all_chapters(
        chapters, book_name, config, character_map=character_map,
        resume=(not args.fresh) or args.offline, offline=args.offline
    )

    # 检查是否有失败的章节
    if failed_results:
        log.info(f"\n⚠️ 有 {len(failed_results)} 个章节分割失败，是否继续生成音频？")
        log.info("   失败章节将被跳过。")

    if not success_results:
        log.info("\n❌ 没有成功分割的章节，无法生成音频")
        return

    # 全书音色表（阶段1 可能带出角色表之外的角色，一并纳入）
    from collections import Counter
    counts = Counter(line.character for r in success_results for line in r.lines)
    cast_file = output_dir / "cast.json"
    cast = None if args.rebuild_cast else load_cast(cast_file)
    if cast:
        log.info(f"\n🎭 复用已有音色表: {cast_file}")
    else:
        cast = build_cast(roster, config, extra_characters=dict(counts))
        save_cast(cast, cast_file)
        log.info(f"\n💾 音色表已保存: {cast_file}")
    print_cast(cast)

    # ============================================================
    # 覆盖率分析
    # ============================================================
    log.info(f"\n{'='*60}")
    log.info("  覆盖率详细分析")
    log.info(f"{'='*60}")

    coverage_reports = []
    for result in success_results:
        report = analyze_coverage(
            original_text=result.chapter.text,
            lines=result.lines,
            chapter_title=result.chapter.title
        )
        coverage_reports.append(report)
        print_coverage_report(report, verbose=(report.coverage < 0.9))

    # 打印汇总
    print_summary(coverage_reports)

    # 如果只分割不生成
    if args.split_only:
        log.info("\n✅ 分割完成（--split-only 模式）")
        return

    # ============================================================
    # 阶段2: TTS生成
    # ============================================================
    all_output_files = await generate_all_audio(
        success_results,
        book_name,
        config,
        cast,
        skip_existing=not args.restart,  # 已存在的章节直接复用，支持断点续跑；--restart 强制重合成
        restart=args.restart,
        keep_segments=args.keep_segments,
    )

    # 完成
    log.info(f"\n{'='*60}")
    log.info("  生成完成!")
    log.info(f"{'='*60}")
    log.info(f"  成功章节: {len(success_results)}/{len(chapters)}")
    log.info(f"  音频文件: {len(all_output_files)} 个")
    log.info(f"  输出目录: {output_dir}")
    log.info("\n🎉 有声书生成完成！")


if __name__ == "__main__":
    asyncio.run(main())
