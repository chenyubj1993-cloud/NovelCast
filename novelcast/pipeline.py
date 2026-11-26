"""把「书 → 音频」的编排收在一个函数里，CLI 和旧脚本共用。

阶段 0：角色表  阶段 1：LLM 分割  阶段 2：TTS 合成
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from novelcast.cast_manager import build_cast, load_cast, print_cast, save_cast
from novelcast.character_registry import (
    load_roster,
    roster_to_prompt_map,
    save_roster,
)
from novelcast.config_manager import ConfigManager
from novelcast.coverage_analyzer import (
    analyze_coverage,
    print_coverage_report,
    print_summary,
)
from novelcast.log import log


async def run_book(
    chapters,
    book_name: str,
    config: ConfigManager,
    *,
    output_dir: Optional[Path] = None,
    offline: bool = False,
    fresh: bool = False,
    restart: bool = False,
    keep_segments: bool = False,
    rebuild_roster: bool = False,
    rebuild_cast: bool = False,
    split_only: bool = False,
    audio_format: str = "wav",
) -> Dict[str, object]:
    """对给定章节跑完整流水线，返回 {output_dir, audios, chapters}。"""
    from novelcast.engine import _roster_from_scripts, split_all_chapters

    output_dir = Path(output_dir) if output_dir else config.get_output_dir(book_name)
    if fresh and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 阶段 0：角色表（roster_mode=off 时跳过，试听单章不必先扫全书）
    roster_mode = str(config.config.get("roster_mode", "full")).lower()
    roster_file = output_dir / "characters.json"
    if roster_mode == "off":
        log.info("\n🎭 roster_mode=off：跳过全书角色表预扫，边分边认角色")
        roster = {"version": 1, "characters": {}}
        character_map = {}
    else:
        roster = None if rebuild_roster else load_roster(roster_file)
        if roster:
            log.info(f"\n🎭 复用角色表: {len(roster['characters'])} 个角色（{roster_file.name}）")
        elif offline:
            log.info("\n" + "=" * 60)
            log.info("  阶段0: 离线模式，从已有剧本汇总角色")
            log.info("=" * 60)
            roster = _roster_from_scripts(output_dir)
            save_roster(roster, roster_file)
        else:
            from novelcast.character_registry import build_roster_async
            from novelcast.dialogue_splitter import get_async_llm_client

            log.info("\n" + "=" * 60)
            log.info("  阶段0: 全书角色抽取")
            log.info("=" * 60)
            roster = await build_roster_async(chapters, book_name, get_async_llm_client(), config)
            save_roster(roster, roster_file)
        character_map = roster_to_prompt_map(roster)

    # 阶段 1：分割
    success_results, failed_results = await split_all_chapters(
        chapters,
        book_name,
        config,
        character_map=character_map,
        resume=(not fresh) or offline,
        offline=offline,
    )
    if failed_results:
        log.info(f"\n⚠️ 有 {len(failed_results)} 个章节分割失败，已跳过")
    if not success_results:
        log.info("\n❌ 没有成功分割的章节，无法生成音频")
        return {"output_dir": output_dir, "audios": [], "chapters": 0}

    # 音色表
    counts = Counter(line.character for r in success_results for line in r.lines)
    cast_file = output_dir / "cast.json"
    cast = None if rebuild_cast else load_cast(cast_file)
    if cast:
        log.info(f"\n🎭 复用已有音色表: {cast_file}")
    else:
        cast = build_cast(roster, config, extra_characters=dict(counts))
        save_cast(cast, cast_file)
    print_cast(cast)

    # 覆盖率
    log.info("\n" + "=" * 60)
    log.info("  覆盖率详细分析")
    log.info("=" * 60)
    reports = [
        analyze_coverage(
            original_text=r.chapter.text,
            lines=r.lines,
            chapter_title=r.chapter.title,
        )
        for r in success_results
    ]
    for report in reports:
        print_coverage_report(report, verbose=report.coverage < 0.9)
    print_summary(reports)

    if split_only:
        log.info("\n✅ 分割完成（--split-only）")
        return {"output_dir": output_dir, "audios": [], "chapters": len(success_results)}

    # 阶段 2：TTS
    from novelcast.engine import generate_all_audio

    audios = await generate_all_audio(
        success_results,
        book_name,
        config,
        cast,
        skip_existing=not restart,
        restart=restart,
        keep_segments=keep_segments,
    )

    m4b_path = None
    if audio_format == "m4b" and audios:
        from novelcast.m4b import build_m4b

        titles = [Path(p).stem.split("_", 1)[-1] for p in audios]
        m4b_path = build_m4b(
            audios,
            titles,
            Path(output_dir) / f"{book_name}.m4b",
            title=book_name,
            artist=config.config.get("author") or None,
        )
        log.info(f"✅ M4B 已导出：{m4b_path}")
    return {
        "output_dir": output_dir,
        "audios": audios,
        "chapters": len(success_results),
        "m4b": m4b_path,
    }


def plan(chapters, chars_per_minute: float = 282.0) -> List[Dict[str, object]]:
    """不调用任何模型，估算时长与分段数（给 --dry-run 用）。"""
    rows = []
    for ch in chapters:
        chars = len(ch.text)
        minutes = chars / chars_per_minute if chars_per_minute else 0
        rows.append(
            {
                "number": ch.number,
                "title": ch.title,
                "chars": chars,
                "segments": max(1, round(chars / 37)),  # 实测约 37 字/段
                "minutes": round(minutes, 1),
            }
        )
    return rows
