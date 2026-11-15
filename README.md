# NovelCast - 多角色有声书生成器

把小说自动拆成「旁白 / 角色对白 + 情绪」，为每个角色分配固定音色，逐段合成音频并合并成有声书。
名字取自 Novel + Cast（角色阵容）。

## 工作流程

1. **阶段 0 · 全书角色表**：分片读全书，抽取角色（姓名、别名、性别、年龄、身份），写入 `output/<书名>/characters.json`，作为后续标注的枚举约束。
2. **阶段 1 · 剧本标注**：按块并发调用 LLM，把正文拆成 `{character, text, emotion}`；提示词带上角色表，减少「同一个人换了称呼就变成新角色」。
3. **全书音色表**：`output/<书名>/cast.json` 一次性给所有角色分配音色（旁白固定、同性别尽量不撞音、别名复用同一音色）。
4. **阶段 2 · TTS**：逐段合成并按章节合并；默认不清空输出，已生成的章节和片段自动跳过，可断点续跑。

## 项目结构

```
NovelCast/
├── novelcast/                  # 核心包（可 pip install）
│   ├── cli.py                 # novelcast 命令（run / doctor / config）
│   ├── pipeline.py            # 三段流水线编排
│   ├── config_manager.py      # 配置管理
│   ├── novel_reader.py        # 小说读取与章节分割（txt/epub/docx/doc）
│   ├── character_registry.py  # 全书角色表抽取/合并
│   ├── cast_manager.py        # 全书音色分配与持久化
│   ├── llm_cache.py           # LLM 分割结果磁盘缓存
│   ├── dialogue_splitter.py   # LLM对话分割（角色表约束 + 缓存）
│   ├── local_tts.py           # 本地 TTS 逐行合成/拼接/断点续跑
│   ├── tts_providers.py       # IndexTTS-2.5 / edge 提供方
│   ├── pronunciation.py       # 多音字标注（<字|拼音>）
│   ├── script_qa.py           # 剧本对齐与自动修复
│   ├── voice_assigner.py      # 旧版逐章音色分配（保留兼容）
│   ├── tts_generator.py       # 云端 TTS（mimoai）
│   └── audio_processor.py     # 音频合并与切分
├── scripts/                    # 独立脚本（生成/修复/音色库/抓数据）
├── tests/                      # pytest 单测（38 个）
├── tools/dev/                  # 开发期一次性脚本（vendored 依赖、迁移）
├── .github/workflows/ci.yml    # GitHub Actions
├── config/
│   ├── settings.json          # 主配置（含密钥，不提交）
│   └── settings.example.json  # 配置示例
├── input/                     # 输入小说
├── output/<书名>/             # 剧本、角色表、音色表、音频
├── llm_cache/<书名>/          # 分割缓存
└── README.md
```

## 快速开始

### 0. 一条命令（推荐）

```bash
pip install -e ".[dev]"          # 轻量依赖；torch / IndexTTS 运行时另装
novelcast doctor                 # 检查依赖、CUDA、模型目录
novelcast run input/全职高手.epub -n 2 --dry-run   # 先看计划：字数/段数/预计时长
novelcast run input/全职高手.epub -n 2 -o output/全职高手
```

- 全部参数见 `novelcast run --help`；`--tts edge` 可以不下载模型先跑通整条流程。
- 输出目录优先级：`-o/--output` > `config/settings.json` 的 `output_dir` > 默认 `output/`；每本书会自动加 `<书名>_有声书` 子目录。
- 输入格式：`.txt` / `.epub` / `.docx` / `.doc`（`.mobi` 需先转换）。
- 旧脚本 `python scripts/generate.py ...` 仍然可用，但 `-c` 在那里表示「前 N 章」，而 `novelcast run` 的 `--chapters 2` 表示「第 2 章」，两者含义不同。

### 1. 配置API

从示例文件创建配置：

```bash
cp config/settings.example.json config/settings.json
```

编辑 `config/settings.json`，填入你的API配置：

```json
{
  "llm_api": {
    "base_url": "https://api.mimoai.com/v1",
    "api_key": "你的LLM API密钥",
    "model": "mimo-v2.5-pro"
  },
  "tts_api": {
    "base_url": "https://api.mimoai.com/v1",
    "api_key": "你的TTS API密钥",
    "model": "mimo-v2.5-pro"
  }
}
```

> **注意**：LLM和TTS的API配置是分开的，可以使用不同的服务商和密钥。如果你使用同一个服务商，可以填相同的URL和密钥。

### 2. 测试API连接

```bash
python scripts/test_api.py
```

### 3. 生成有声书

```bash
# 生成全部章节
novelcast run input/测试短文.txt

# 只生成前 2 章
novelcast run input/测试短文.txt -n 2

# 只生成第 2 章
novelcast run input/测试短文.txt --chapters 2

# 重跑：保留剧本、重合成音频
novelcast run input/测试短文.txt -n 2 --restart

# 离线：直接复用已有剧本，不调用 LLM（剧本可由人工或其他模型生成）
novelcast run input/全职高手.epub --chapters 1 --offline --split-only
```

## 配置说明

### 核心配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `generation.chunk_size` | 按此字数分块，每块再固定分成llm_concurrency段 | 1500 |
| `generation.min_split_length` | 递归拆分最小长度（低于此值使用fallback） | 5 |
| `generation.max_duration_per_file` | 单个音频文件最大时长（秒） | 900 (15分钟) |
| `generation.silence_between_segments` | 段落间静音时长（秒） | 0.5 |
| `concurrency.llm_concurrency` | LLM并发数（每个块固定分成几段） | 3 |
| `concurrency.tts_concurrency` | TTS并发数 | 5 |
| `tts.min_chars` | TTS最小字符数（低于此值跳过） | 2 |
| `rate_limit.llm_rpm` | LLM每分钟请求数限制 | 30 |
| `rate_limit.tts_rpm` | TTS每分钟请求数限制 | 60 |

### 音色配置

```json
{
  "voice_presets": {
    "冰糖": "ice_candy",
    "苏打": "soda",
    "default": "ice_candy"
  }
}
```

### 音色库（voice bank，真人音色）

内置的 8 个音色是 edge-tts 合成的（微软神经网络语音），克隆出来仍带电子感。想要更自然的声音，可以从开源语料构建自己的音色库：

```powershell
# 1) 朗读库（AISHELL-3 子集，主要给群杂）
python scripts/fetch_aishell3_subset.py --speakers 40 --per-speaker 2
python scripts/build_voice_bank.py data\aishell3_hf --count 24

# 2) 播音腔库（WenetSpeech4TTS Premium 子集，主要给次要角色）
#    流式读 tar.gz，取够指定量就断开，不会下完整 8.5GB
python scripts/fetch_ws4tts.py --max-bytes 2000MB
python scripts/build_voice_bank.py data\ws4tts --count 28 --style broadcast `
    --source-name ws4tts --id-prefix WS --infer-gender --merge
```

产物：

- `output/_refs/A3-SSB0001.wav` / `WS-S00023.wav` 等参考音（24kHz、峰值 −6dBFS、≤12 秒）
- `output/_refs/voice_bank.json`：说话人、性别、年龄、来源、`style`（read/broadcast）、质量分

`cast_manager` 会自动读这个文件（也可以显式配置 `"voice_bank": "output/_refs/voice_bank.json"`）。默认的选音策略是：

- **旁白 + 主要角色**（出场最多的前 6 个）：沿用原来的 edge 音色，朗读稳、辨识度高；
- **次要角色**：优先用播音腔库（`WS-*`），不够时回退朗读库，按角色性别挑；
- **群杂**（众人/路人/未知…）：用朗读库，并预留 16 条不分配给任何角色；群杂**逐条轮换**、男女交替，同一场景里不会一个人从头念到尾。

> 许可：AISHELL-3 是 Apache-2.0；WenetSpeech4TTS 是 CC BY-NC 4.0（仅非商用），商用请换成 MagicData 等授权语料。

主要角色数量可以调：

```json
{
  "voice_bank": "output/_refs/voice_bank.json",
  "main_character_count": 6,
  "main_characters": ["叶秋", "苏沐橙"]
}
```

想指定某个角色用某条音色，直接在 `character_voices` 里写库里的 id（写内置音色名也可以）：

```json
{
  "character_voices": { "旁白": "冰糖", "叶秋": "白桦", "吧台的小姑娘": "A3-SSB0011" }
}
```

> 许可：AISHELL-3 是 Apache-2.0，可商用；Emilia（CC BY-NC 4.0）、WenetSpeech（申请制非商用）只能自己用。真人声音还涉及声音权，公开发布前请确认授权。

## 人物映射功能

### 问题背景
由于小说会被分割成多个chunk分别处理，可能会出现以下问题：
1. 同一个人物在不同chunk中被分配不同的音色
2. LLM错误地将描述性词语（如"些调皮地"、"没好气地"）当作角色名
3. 代词（如"他"、"我"）被当作角色处理

### 解决方案

#### 1. 全局人物映射表
- 第一次分割后自动建立人物映射表
- 后续分割时传入已知映射，保持一致性
- 映射表在生成新书时自动清空

#### 2. 角色名验证
系统会自动过滤以下无效角色名：
- **代词**：他、她、它、我、你、我们、他们
- **描述性词语**：些调皮地、没好气地、开心地、生气地
- **动作描述**：说、道、喊、问、笑、哭

#### 3. 改进的提示词
LLM提示词中明确说明了角色识别规则，减少错误识别。

### 查看人物映射
生成完成后，系统会打印全局人物映射表：
```
🎭 全局人物映射表:
   小明 -> 冰糖
   妈妈 -> 茉莉
   爸爸 -> 苏打
   老师 -> 白桦
```

### 测试人物映射
```bash
python scripts/test_character_map.py
```

## 输出结构

```
output/
└── {书名}_有声书/
    ├── 001_章节标题.wav          # 章节音频（按时长切分）
    ├── 001_章节标题_part02.wav   # 超过15分钟会自动切分
    ├── 001_章节标题_script.json  # 对话脚本（用于字幕）
    ├── 002_章节标题.wav
    └── ...

llm_raw_responses/
└── {书名}/
    ├── chapter_001/
    │   ├── block001_seg000.json              # LLM原始响应（按块_段组织）
    │   ├── block001_seg000_readable.txt      # 可读文本（方便对照检查）
    │   ├── block001_seg001.json
    │   └── ...
    └── chapter_002/
        └── ...
```

### 可读文本格式

`*_readable.txt` 文件提供清晰的对照格式：

```
=== 第一章 相遇_block001_seg000 ===
解析时间: 2026-05-22 12:29:30

共 11 段:

  1. [旁白] 小明走在放学的路上，看到妈妈在门口等他。
  2. [旁白] 小明开心地喊道
     情绪: happy
  3. [小明] 妈妈，我回来了！
     情绪: happy
  4. [妈妈] 今天在学校怎么样？
     情绪: happy
  ...
```

**用途**：
- 快速检查LLM分割是否正确
- 对照原文查看是否有遗漏
- 验证角色识别是否准确

## 模块说明

### config_manager.py
- 统一配置管理
- 支持JSON配置文件
- 提供默认配置和用户配置合并

### novel_reader.py
- 支持 `.txt`, `.docx`, `.doc`, `.epub` 格式（epub 按 spine 顺序抽取正文）
- 自动识别章节标题；章节很多时丢弃 <100 字的目录页碎片
- 返回结构化的章节数据

### dialogue_splitter.py
- 使用LLM分割对话和旁白
- **两层分割架构**：先按 `chunk_size` 分块，再每块固定分成 `llm_concurrency` 段并发处理
- 块内并发、块间串行：同一块的各段并发执行，块之间按顺序串行处理
- 递归二分法处理内容审核拒绝（异步版本，不阻塞事件循环）
- API超时90秒：超时且字数>1000字时直接拆分，不重试
- 自动验证覆盖率（最低70%）
- 失败时自动降级到简单分割

### voice_assigner.py
- 自动识别角色
- 分配音色ID
- 支持自定义角色音色映射
- **全局人物映射表**：保持跨章节角色一致性

### tts_generator.py
- 异步批量生成TTS音频
- 自动处理长文本分割
- 速率限制和错误重试

### audio_processor.py
- WAV文件合并
- 按时长自动切分
- 静音插入

### script_qa.py
- 原文与剧本逐字对齐（SequenceMatcher），按「实际文字」算覆盖率
- 引号/标点被合并不算丢字，单独统计
- 自动补回两类缺失：结尾被截断的整段（补旁白）、被吃掉的「XX说/问」提示语（补旁白行）

## 剧本质量校验

分割完成后会打印一行对齐结果：

```
🔍 对齐检查: 内容覆盖 100.00%，缺失 0 字 / 0 处（另有 130 个标点被合并，不影响朗读）
```

- **内容覆盖**：按实际文字计算，引号、逗号被合并进对白不算丢失。
- **缺失**：录音里会真的少掉的字，按位置列出前 3 处。
- 自动修复：`🩹 修复: 补结尾 N 字、补回 M 处「XX说/问」`。LLM 常把「”朱先生问：“」整段吞掉，
  导致听感上少了「谁在说」；这里会补回一行旁白。
- 角色表外的人物（如只出现一次的「张秀才」）不再回退旁白，而是按名字稳定分配一个群杂音色，
  重跑结果一致；「众人/路人/未知」仍按男女交替轮换。
- 目录、封面、版权、全文这类伪章节会被合并进下一章，避免 `-c N` 的编号错位。

## 与原版本对比

| 特性 | 原版本 | 模块化版本 |
|------|--------|------------|
| 代码组织 | 单文件1711行 | 7个独立模块 |
| 配置管理 | 硬编码 | JSON配置文件 |
| 角色一致性 | 每章独立分配音色 | 全书角色表 + cast.json |
| 断点续跑 | 每次清空输出 | 剧本/音频/LLM 缓存三级复用 |
| 输出组织 | 按时间戳 | 按书名/章节 |
| 章节处理 | 全文处理 | 逐章处理 |
| 时长控制 | 无限制 | 自动切分（默认15分钟） |
| LLM响应 | 不保存 | 按书名/章节保存 |
| 可扩展性 | 差 | 良好 |

## 多角色与断点续跑

### 新增参数

| 参数 | 作用 |
|------|------|
| `--fresh` | 清空 `output/`、`llm_cache/`、`llm_raw_responses/` 后重跑 |
| `--restart` | 保留剧本和角色表，丢弃逐行分段缓存、重新合成音频 |
| `--rebuild-roster` | 忽略已有 `characters.json`，重新抽取角色表 |
| `--offline` | 只读已有 `*_script.json`，不调用 LLM；角色表从 `characters.json` 或剧本汇总 |
| `--keep-segments` | 整章合成后保留 `_temp_XXX/` 分段缓存（默认清理，省约一半磁盘） |

不带 `--fresh` 时：章节已有 `*_script.json` 就直接复用、不再调用 LLM；章节已有合并音频就跳过 TTS；单段分割结果按 `sha1(书名 + 模型 + 提示词版本 + 角色表 + 原文)` 命中磁盘缓存。

复用剧本前会做一次逐字对齐：如果旧剧本只覆盖本章不到 98%（例如 `--first-chars` 试跑留下的半章剧本），会打印警告并重新分割，不会拿残缺剧本生成音频。

### 断点续跑（本地 TTS 逐行级）

本地合成（IndexTTS-2 / edge）把每章拆成 `seg_0000.wav`、`seg_0001.wav`…，旁边维护 `segments.json`：

```json
{"version": 1, "items": {"0": {"sha": "…", "character": "旁白", "emotion": "平静"}}}
```

- 每合成完一段就写清单 + 原子替换 wav（先写 `.part` 再 `os.replace`），进程被杀也不会留下半截文件；
- 重跑时只有 `sha1(text + character + emotion)` 一致、且 wav 能正常打开的分段才复用，改了台词或换了音色会自动重合成；
- 所有分段齐了才拼接整章，整章 wav 同样先写 `.part` 再替换，已存在的整章音频直接跳过；
- 因此 Ctrl+C、断电、关机后重跑同一条命令即可，日志会打印 `♻️ 断点续跑：复用 N/M 段缓存`。
- 合成时会把超过 40 字的行自动按句号/问号/分号再切（单句仍超长时按逗号，最后硬切），日志打印 `✂️ 长句拆分：74 行 -> 113 段`；切分无损，不改变剧本文件。上限设为 40 是为了避开 IndexTTS 在 8GB 显存下的 low-VRAM 内部切分（`infer_v2_5.py` 会对 >40 字的文本自行再切并插入 200ms 静音），否则一句中间会莫名停顿。
- 整章成功落盘后默认删除 `_temp_XXX/` 分段缓存（可省约一半磁盘）；需要保留缓存重跑时加 `--keep-segments`。中途失败不会清理，保证可续跑。

> 说明：IndexTTS-2 是串行推理，8GB 显存下无法并行多段；"续跑"解决的是中断后不白跑，而不是提升单章速度。

### 产物说明

| 文件 | 内容 |
|------|------|
| `output/<书名>/characters.json` | 全书角色表：`name / aliases / gender / age / role / appearances` |
| `output/<书名>/cast.json` | 全书音色表：`voices`（角色→音色）与旁白音色 |
| `output/<书名>/*_script.json` | 每章剧本：`lines[] = {character, text, emotion, voice}` |
| `output/<书名>/*_partNN.wav` | 最终音频（按时长切分） |

角色表可以手工编辑后直接重跑（不要加 `--rebuild-roster`）；`cast.json` 里也能把某个角色的音色改成 `voice_presets` 中的任意名字。

### 已知限制

- 角色表只覆盖本次选中的章节；只选部分章节时，未选章节里的角色不会提前出现。
- 提示词里的角色表是「参考名单」，LLM 仍可能输出表外角色；表外角色统一回落到旁白音色，并在日志中列出。
- 中文省略主语的连续对话仍可能标错说话人，建议先跑 `--split-only` 检查 `*_readable.txt`。

## 本地 TTS（IndexTTS-2，可选）

云端 TTS（mimoai）需要联网和 key；本仓库另外接了本地 IndexTTS-2：8GB 显存可跑、零样本克隆音色、支持情绪文本。

### 准备

- 模型放在 `models/IndexTTS-2/`（`gpt.pth`、`s2mel.pth`、`qwen0.6bemo4-merge/`、`config.yaml` 等，约 4.6GB）
- 依赖在 `.vendor/`（torch 2.11.0+cu128、transformers 4.52.1、soundfile 0.14 等），运行前设置 `PYTHONPATH=D:\code\NovelCast\.vendor`
- 角色参考音由 edge-tts 自动生成到 `output/_refs/<角色>.mp3`，也可以换成真人录音

### 用法 A：单独合成某章剧本

```powershell
$env:PYTHONPATH = "D:\code\NovelCast\.vendor"
python novelcast/local_tts.py "output/全职高手_有声书/002_第0002章 C区47号_script.json" `
  -o output/ch2.wav --cast "output/全职高手_有声书/cast.json"
```

### 用法 B：接入整条流水线

在 `config/settings.json` 中设置 `"tts": {"provider": "indextts2"}`，之后照常运行 `novelcast run input/xxx.epub -n 2`；阶段 2 会自动走本地 TTS，并跳过已存在的章节音频。

### 性能与注意

- RTX 5060 Laptop 8GB 实测 RTF ≈ 1.1–1.9（1 秒音频约需 1–2 秒），首次加载模型约 1–2 分钟，同进程内复用
- IndexTTS-2 输出 22.05kHz，本项目拼接时统一重采样到 24kHz
- 单段音频缓存在 `output/_segments/seg_XXXX.wav`，重跑只补缺失段
- 情绪字段（`emotion`）会作为 `emo_text` 传给 IndexTTS-2；「平静」不传

### IndexTTS-2.5：多音字与语速

IndexTTS-2.5 增加了**行内发音标注**（`<字|拼音>`）和**时长控制**（`duration_factor`），2.x 没有这两个能力。

下载权重（约 5.1GB）：

```powershell
modelscope download --model IndexTeam/IndexTTS-2.5 --local_dir models/IndexTTS-2.5
# 或 huggingface-cli download IndexTeam/IndexTTS-2.5 --local-dir models/IndexTTS-2.5
```

在 `config/settings.json` 里切换：

```json
"tts": {
  "provider": "indextts2",
  "model_version": "2.5",
  "indextts_model_dir": "models/IndexTTS-2.5",
  "duration_factor": 1.0,
  "lang": "zh",
  "use_qwen_emo": null
}
```

- `duration_factor`：0.5–2.0，越小越快（1.0 为原速）
- `use_qwen_emo`：`null` 自动；显存紧张时设 `false`，只保留参考音情绪

**情绪**：剧本每行都带 `emotion` 标签。默认 `emotion_mode: "text"`，会把标签转成中文提示（如"有些不悦，语气稍沉"），并做**温和的**语速调整（生气 0.95×、悲伤 1.06×，幅度刻意收窄，避免忽快忽慢）：

```json
"emotion_mode": "text",   // text | vector | off
"emo_alpha": 0.55         // 0~1 情绪强度；1.0 最满，但容易显得吵闹
```

`"vector"` 改用 8 维情绪向量（happy/angry/sad/afraid/disgusted/melancholic/surprised/calm），`"off"` 完全关闭。

已有剧本如果 neutral 偏多，可以用 LLM 补标（只改 emotion、不动文本，拿不准就不改）：

```powershell
python scripts/relabel_emotion.py "output/全职高手_有声书/001_*_script.json"          # 预览
python scripts/relabel_emotion.py "output/全职高手_有声书/001_*_script.json" --write  # 写回
```

**响度与停顿**：整章拼接后按 **-18 LUFS** 归一（`loudness_lufs`），峰值不超过 0.95；旁白后停 0.4 秒，连续对白之间只停 0.15 秒（`silence_narration` / `silence_dialogue`），不再全章固定 0.3 秒。

> 目标设成 -16 时，人声的峰均比会让增益被峰值保护挡住（实测只能到 -18.2），所以默认取 -18；要更响就需要加限幅器，代价是可能轻微失真。

**自动验收**：每章合成结束会打印

```
📊 自检: 282 字/分 · 最长段 5.2s · -16.0 LUFS · 峰值 0.95
```

语速不在 220–340 字/分、或单段超过 30 秒时给出告警，建议抽听。

**多音字**：把词和拼音写进 `config/pronunciation.json`，合成前会自动转成 `<重|CHONG2><庆|QING4>`：

```json
{
  "words": {
    "重庆": "CHONG2 QING4",
    "银行": "YIN2 HANG2",
    "兴欣": "XING1 XIN1"
  }
}
```

拼音按字用空格对齐；也可以直接写 `<行|XING2>` 这样的完整标注。扫描剧本里的多音字风险词：

```powershell
python scripts/scan_pronunciation.py "output/全职高手_有声书/002_*_script.json"
# 让 DeepSeek 判断读音并写回：
python scripts/scan_pronunciation.py ... --llm --write
```

> 只有 `model_version` 为 2.5 时才会启用标注；用 2.x 会把 `<重|CHONG2>` 原样念出来。

## 故障排除

### asyncio.Lock() 错误
已修复。使用延迟创建Lock的方案，确保绑定到正确的事件循环。

### 并发架构说明（2026-05-22更新）

**两层分割架构**：
1. **章节级**：按 `chunk_size`（默认1500字）将章节分成多个块
2. **块级**：每个块固定分成 `llm_concurrency`（默认3）段并发处理

**执行流程**：
```
章节 (3000字)
  ├── 块1 (1500字) → 段1(500字) + 段2(500字) + 段3(500字) → 并发3个
  └── 块2 (1500字) → 段1(500字) + 段2(500字) + 段3(500字) → 并发3个
```

**特点**：
- 块内并发：同一块的各段使用 `asyncio.gather` 并发执行
- 块间串行：块1完成后才处理块2
- 章节只对音频合并有用：同一章的音频会合并成一个文件

### API超时处理（2026-05-22更新）
- API调用超时：90秒
- 超时且字数>1000字：直接拆分，不重试（明显是字数太多导致处理慢）
- 超时且字数≤1000字：最多重试3次（递增等待5秒、10秒）

### API连接失败
1. 检查 `config/settings.json` 中的API配置
2. 运行 `python scripts/test_api.py` 测试连接
3. 检查网络连接和API密钥

### 覆盖率过低
如果LLM分割覆盖率低于70%，系统会自动降级到简单分割。可以尝试：
1. 减小 `chunk_size` 配置
2. 检查原文格式是否规范

## 开发说明

### 添加新模块
1. 在 `novelcast/` 目录创建新文件
2. 在 `novelcast/__init__.py` 中导出
3. 在需要的地方导入使用

### 修改配置
使用 `scripts/configure.py` 或直接编辑 `config/settings.json`

## 许可证

MIT License
