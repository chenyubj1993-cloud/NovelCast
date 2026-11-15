#!/usr/bin/env python
"""NovelCast 命令行入口：novelcast run book.epub -o out/"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from novelcast.log import log

# 本地依赖（torch/transformers 等）装在 .vendor 里，命令行入口自动挂上去
_VENDOR = Path(__file__).resolve().parent.parent / ".vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from novelcast.config_manager import ConfigManager
from novelcast.log import setup as setup_logging


def _parse_chapters(spec: str):
    """'1,3,5-7' -> [1,3,5,6,7]"""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def cmd_run(args) -> int:
    from novelcast.novel_reader import read_novel, split_chapters
    from novelcast.pipeline import plan, run_book

    config = ConfigManager(args.config)
    if args.output:
        config.output_override = Path(args.output).expanduser().resolve()
    config.apply_tts_overrides(
        provider=args.tts,
        model_version=args.model_version,
        duration_factor=args.speed,
        emotion_mode=args.emotion_mode,
    )

    book_name, content = read_novel(args.input)
    chapters = split_chapters(content)
    if args.first_chapters:
        chapters = chapters[: args.first_chapters]
    if args.first_chars:
        from scripts.generate import _filter_chapters_content

        chapters = _filter_chapters_content(chapters, None, args.first_chars)
    if args.chapters:
        wanted = _parse_chapters(args.chapters)
        chapters = [chapters[i - 1] for i in wanted if 1 <= i <= len(chapters)]
    if not chapters:
        log.info("❌ 没有可处理的章节")
        return 2

    if args.dry_run:
        rows = plan(chapters)
        log.info(f"\n📖 {book_name}：{len(chapters)} 章，{sum(r['chars'] for r in rows)} 字")
        for r in rows:
            log.info(
                f"  {r['number']:>4}. {r['title'][:30]:<30} "
                f"{r['chars']:>7} 字  ~{r['segments']:>4} 段  ~{r['minutes']:>5.1f} 分钟"
            )
        total = sum(r["minutes"] for r in rows)
        log.info(f"\n  预计音频 {total:.1f} 分钟（{total/60:.1f} 小时）· 输出目录 {config.get_output_dir(book_name)}")
        return 0

    result = asyncio.run(
        run_book(
            chapters,
            book_name,
            config,
            output_dir=Path(args.output) if args.output else None,
            offline=args.offline,
            fresh=args.fresh,
            restart=args.restart,
            keep_segments=args.keep_segments,
            rebuild_roster=args.rebuild_roster,
            rebuild_cast=args.rebuild_cast,
            split_only=args.split_only,
        )
    )
    log.info(f"\n🎉 完成：{len(result['audios'])} 个音频 → {result['output_dir']}")
    return 0


def cmd_doctor(args) -> int:
    """检查运行环境：Python、关键依赖、模型目录、配置。"""
    import importlib

    ok = True
    log.info(f"Python {sys.version.split()[0]}  ({sys.executable})")
    for mod, label in [
        ("numpy", "numpy"),
        ("soundfile", "soundfile"),
        ("httpx2", "httpx2"),
        ("openai", "openai"),
        ("torch", "torch"),
        ("edge_tts", "edge-tts"),
    ]:
        try:
            importlib.import_module(mod)
            log.info(f"  ✅ {label}")
        except Exception as exc:
            ok = False
            log.info(f"  ❌ {label}: {exc}")

    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            cap = ".".join(map(str, torch.cuda.get_device_capability(0)))
            log.info(f"  🎮 CUDA 可用：{name} (sm_{cap.replace('.', '')})")
        else:
            log.info("  ⚠️ CUDA 不可用，只能用 edge 或 CPU")
    except Exception:
        pass

    config = ConfigManager(args.config)
    model_dir = Path(config.tts.indextts_model_dir)
    log.info(f"  模型目录：{model_dir} {'✅' if model_dir.exists() else '❌ 不存在'}")
    if not model_dir.exists():
        ok = False
        log.info("     参考 README「模型准备」把权重下载到该目录")
    log.info(f"  TTS provider：{config.config['tts']['provider']}")
    return 0 if ok else 1


def cmd_config(args) -> int:
    config = ConfigManager(args.config)
    import json

    log.info(json.dumps(config.config, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="novelcast", description="把小说变成多角色有声书")
    p.add_argument("--config", help="配置文件路径（默认 config/settings.json）")
    p.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    p.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="一条命令：文档 → 音频")
    r.add_argument("input", help="txt / epub / docx / doc 路径")
    r.add_argument("-o", "--output", help="输出目录（默认 output/<书名>_有声书）")
    r.add_argument("-n", "--first-chapters", type=int, help="只处理前 N 章")
    r.add_argument("--chapters", help="章节号，如 1,3,5-7")
    r.add_argument("--first-chars", type=int, help="每章只取前 N 字（试听）")
    r.add_argument("--tts", choices=["indextts2", "edge", "openai", "mimoai"], help="TTS 引擎")
    r.add_argument("--model-version", choices=["2", "2.5"], help="IndexTTS 版本")
    r.add_argument("--speed", type=float, help="语速倍率 0.5~2.0（越小越快）")
    r.add_argument("--emotion-mode", choices=["text", "vector", "off"], help="情绪驱动方式")
    r.add_argument("--offline", action="store_true", help="只用已有剧本，不调 LLM")
    r.add_argument("--split-only", action="store_true", help="只分割，不合成")
    r.add_argument("--dry-run", action="store_true", help="只打印计划")
    r.add_argument("--fresh", action="store_true", help="清空输出与缓存后重来")
    r.add_argument("--restart", action="store_true", help="保留剧本，重合成音频")
    r.add_argument("--keep-segments", action="store_true", help="保留分段 wav")
    r.add_argument("--rebuild-roster", action="store_true")
    r.add_argument("--rebuild-cast", action="store_true")
    # 也允许写在子命令后面；SUPPRESS 避免覆盖全局同名字段
    r.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    r.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS)
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("doctor", help="检查环境")
    d.set_defaults(func=cmd_doctor)

    c = sub.add_parser("config", help="打印当前配置")
    c.set_defaults(func=cmd_config)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=getattr(args, "verbose", False), quiet=getattr(args, "quiet", False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
