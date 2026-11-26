"""
小说读取模块
负责读取小说文件、分割章节
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from novelcast.log import log

from .config_manager import INPUT_DIR, get_config


@dataclass
class Chapter:
    """章节数据"""
    number: int  # 章节序号（1-based）
    title: str   # 章节标题
    text: str    # 章节内容


def read_novel(file_path: str) -> Tuple[str, str]:
    """
    读取小说文件

    Args:
        file_path: 文件路径（支持绝对路径或 input/ 下的相对路径）

    Returns:
        (书名, 原文内容)
    """
    path = Path(file_path)

    # 支持相对路径
    if not path.exists():
        path = INPUT_DIR / file_path

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    suffix = path.suffix.lower()
    book_name = path.stem  # 文件名作为书名

    if suffix == ".docx":
        content = _read_docx(path)
    elif suffix == ".doc":
        content = _read_doc(path)
    elif suffix == ".txt":
        content = _read_txt(path)
    elif suffix == ".epub":
        content = _read_epub(path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")

    log.info(f"  📖 读取小说: {path}")
    log.info(f"     总字数: {len(content)}")

    return book_name, content


def _read_txt(path: Path) -> str:
    """读取TXT文件"""
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'utf-16']
    for encoding in encodings:
        try:
            with open(path, 'r', encoding=encoding) as f:
                return f.read().strip().lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法读取文件，尝试的编码都失败: {path}")


def _read_docx(path: Path) -> str:
    """读取DOCX文件"""
    try:
        import docx
        doc = docx.Document(str(path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        raise ValueError(f"读取DOCX文件失败: {e}")


def _read_doc(path: Path) -> str:
    """读取DOC文件（使用Word COM自动化）"""
    abs_path = str(path.resolve())

    try:
        # 尝试使用 Word COM 自动化
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False

        temp_docx = abs_path + "x"
        try:
            doc = word.Documents.Open(abs_path)
            doc.SaveAs2(temp_docx, FileFormat=16)
            doc.Close()
        finally:
            word.Quit()
            pythoncom.CoUninitialize()

        # 读取转换后的DOCX
        import docx
        docx_doc = docx.Document(temp_docx)
        paragraphs = [p.text.strip() for p in docx_doc.paragraphs if p.text.strip()]

        # 清理临时文件
        try:
            os.remove(temp_docx)
        except OSError:
            pass

        return "\n\n".join(paragraphs)

    except ImportError:
        # 如果没有 win32com，尝试使用 mammoth
        try:
            import mammoth
            with open(abs_path, "rb") as f:
                result = mammoth.convert_to_markdown(f)
                return result.value.strip()
        except Exception as e:
            raise ValueError(f"读取DOC文件失败（需要安装 python-docx 或 mammoth）: {e}")

    except Exception as e:
        raise ValueError(f"读取DOC文件失败: {e}")


def _read_epub(path: Path) -> str:
    """读取 EPUB：按 spine 顺序取出各 xhtml 的正文。"""
    import posixpath
    import zipfile

    from lxml import etree
    from lxml import html as lxml_html

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        try:
            container = etree.fromstring(zf.read("META-INF/container.xml"))
        except KeyError:
            raise ValueError("不是有效的 EPUB：缺少 META-INF/container.xml")

        rootfiles = container.xpath("//*[local-name()='rootfile']/@full-path")
        if not rootfiles:
            raise ValueError("EPUB 中找不到 OPF 文件")
        opf_path = rootfiles[0]
        opf_dir = posixpath.dirname(opf_path)
        opf = etree.fromstring(zf.read(opf_path))

        manifest = {}
        for item in opf.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
            item_id = item.get("id")
            href = item.get("href")
            if item_id and href:
                manifest[item_id] = posixpath.normpath(posixpath.join(opf_dir, href))

        spine = [
            manifest[ref.get("idref")]
            for ref in opf.xpath("//*[local-name()='spine']/*[local-name()='itemref']")
            if ref.get("idref") in manifest
        ]

        documents = []
        for name in spine:
            if name not in names:
                continue
            try:
                documents.append(_html_to_text(zf.read(name), lxml_html))
            except Exception:
                continue

    text = "\n\n".join(d for d in documents if d)
    if not text.strip():
        raise ValueError("EPUB 中未解析到正文")
    return text


_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "blockquote", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table",
}


def _html_to_text(data: bytes, lxml_html) -> str:
    """把单个 xhtml 转成按段落分行的纯文本。"""
    doc = lxml_html.fromstring(data)
    body = doc.body if doc.body is not None else doc

    parts = []
    for el in body.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in _BLOCK_TAGS:
            parts.append("\n")
        if el.text:
            parts.append(el.text)
        if el.tail:
            parts.append(el.tail)

    text = "".join(parts)
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def split_chapters(text: str) -> List[Chapter]:
    """
    将文本分割成章节

    Args:
        text: 原文内容

    Returns:
        章节列表
    """
    get_config()

    # 尝试按章节标题分割
    chapter_patterns = [
        r'^第[一二三四五六七八九十百千\d]+章\s*.*$',  # 第X章
        r'^第[一二三四五六七八九十百千\d]+节\s*.*$',  # 第X节
        r'^第[一二三四五六七八九十百千\d]+[问话回幕](?:\s+.*|[：:·、—-].*)?$',  # 第X问 / 第X话 / 第X回
        r'^(序章|序言|楔子|引子|终章|尾声|后记|番外)(?:\s+.*|[：:·、—-].*)?$',
        r'^(プロローグ|エピローグ)(?:\s+.*|[：:·、—-].*)?$',  # 日文轻小说
        r'^Chapter\s*\d+.*$',  # Chapter X
        r'^【\s*第[一二三四五六七八九十百千\d]+[章回话问节]\s*.*】\s*$',  # 【第二问】
        r'^【\s*(序章|序言|楔子|引子|终章|尾声|后记|番外).*】\s*$',
        # 数字标题（"1. 标题"）：必须短、且不以句末标点结尾，避免把正文列表行当章节
        r'^\d+\.\s*[^。！？，,：:]{1,20}$',
    ]

    # 合并所有模式
    combined_pattern = '|'.join(f'({p})' for p in chapter_patterns)

    # 按行分割
    lines = text.split('\n')
    chapters = []
    current_title = "全文"
    current_text = []
    chapter_num = 0

    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
        lines = text.split("\n")

    # 模板页（epub 制作工具残留）："警告：这个文件不要做任何改动" 之类，按行丢掉
    boilerplate_lines = ("title.xhtml", "这个文件不要做任何改动", "书名在title.xhtml")

    for line in lines:
        line_stripped = line.strip()
        if line_stripped and re.match(combined_pattern, line_stripped, re.MULTILINE):
            # 保存之前的章节
            if current_text:
                chapter_num += 1
                chapters.append(Chapter(
                    number=chapter_num,
                    title=current_title,
                    text='\n'.join(current_text).strip()
                ))
            current_title = line_stripped
            current_text = []
        else:
            if any(marker in line for marker in boilerplate_lines):
                continue
            current_text.append(line)

    # 保存最后一个章节
    if current_text:
        chapter_num += 1
        chapters.append(Chapter(
            number=chapter_num,
            title=current_title,
            text='\n'.join(current_text).strip()
        ))

    chapters = [c for c in chapters if c.text.strip()]

    # EPUB/网页来源常夹带目录页碎片：章节很多时丢掉 <100 字的伪章节
    if len(chapters) > 10:
        kept = [c for c in chapters if len(c.text) >= 100]
        dropped = len(chapters) - len(kept)
        if dropped:
            log.info(f"     已忽略 {dropped} 个过短片段（<100字）")
            for i, ch in enumerate(kept, 1):
                ch.number = i
            chapters = kept

    # 目录/封面/全文 这类伪章节：正文并入下一章，避免 -c 的编号错位
    if len(chapters) > 1:
        pseudo_titles = {
            "全文", "目录", "封面", "版权", "内容简介", "作品简介",
            "作者简介", "声明", "免责声明",
        }
        merged: List[Chapter] = []
        carry = ""
        for ch in chapters:
            if ch.title.strip() in pseudo_titles:
                carry = (carry + "\n" + ch.text).strip()
                continue
            if carry:
                ch.text = (carry + "\n" + ch.text).strip()
                carry = ""
            merged.append(ch)
        if carry and merged:
            merged[-1].text = (merged[-1].text + "\n" + carry).strip()
        if len(merged) != len(chapters):
            log.info(f"     已合并 {len(chapters) - len(merged)} 个目录/封面类伪章节")
            for i, ch in enumerate(merged, 1):
                ch.number = i
            chapters = merged

    # 如果没有检测到章节，将整个文本作为一个章节
    if not chapters:
        chapters.append(Chapter(
            number=1,
            title="全文",
            text=text.strip()
        ))

    log.info(f"     章节数: {len(chapters)}")
    preview = chapters if len(chapters) <= 20 else chapters[:10] + chapters[-5:]
    for ch in preview:
        log.info(f"       {ch.number:03d}. {ch.title} ({len(ch.text)}字)")
    if len(chapters) > len(preview):
        log.info(f"       …… 其余 {len(chapters) - len(preview)} 章略")

    return chapters


