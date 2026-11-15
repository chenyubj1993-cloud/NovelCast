$ErrorActionPreference = 'Continue'
$dst = 'D:\code\NovelCast\models\IndexTTS-2.5'
$base = 'https://modelscope.cn/models/IndexTeam/IndexTTS-2.5/resolve/master'
New-Item -ItemType Directory -Force $dst | Out-Null

# expected size in MB; 0 = do not check
$files = @{}
$files['codec.pth'] = 579.2
$files['config.yaml'] = 0
$files['feat1.pt'] = 0.05
$files['feat2.pt'] = 0.4
$files['gpt.pth'] = 3108.6
$files['multilingual_zh_ja_yue_char_del.tiktoken'] = 0.9
$files['s2mel.pth'] = 395.7
$files['wav2vec2bert_stats.pt'] = 0
$files['qwen0.6bemo4-merge/Modelfile'] = 0
$files['qwen0.6bemo4-merge/added_tokens.json'] = 0
$files['qwen0.6bemo4-merge/chat_template.jinja'] = 0
$files['qwen0.6bemo4-merge/config.json'] = 0
$files['qwen0.6bemo4-merge/generation_config.json'] = 0
$files['qwen0.6bemo4-merge/merges.txt'] = 1.6
$files['qwen0.6bemo4-merge/model.safetensors'] = 1136.9
$files['qwen0.6bemo4-merge/special_tokens_map.json'] = 0
$files['qwen0.6bemo4-merge/tokenizer.json'] = 10.9
$files['qwen0.6bemo4-merge/tokenizer_config.json'] = 0
$files['qwen0.6bemo4-merge/vocab.json'] = 2.6

foreach ($f in $files.Keys) {
    $out = Join-Path $dst $f
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    $expectMb = $files[$f]
    if ($expectMb -gt 1) {
        if ((Test-Path $out) -and ((Get-Item $out).Length -gt ($expectMb * 0.97 * 1MB))) {
            Write-Output "skip $f ($([math]::Round((Get-Item $out).Length/1MB,1)) MB)"
            continue
        }
    } elseif ((Test-Path $out) -and ((Get-Item $out).Length -gt 0)) {
        Write-Output "skip $f (small)"
        continue
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    curl.exe -sS -L --retry 3 --max-time 3600 -o $out "$base/$f"
    $len = 0
    if (Test-Path $out) { $len = (Get-Item $out).Length }
    Write-Output ("done {0} {1} MB in {2:N0}s ({3} MB/s)" -f $f, [math]::Round($len/1MB,1), $sw.Elapsed.TotalSeconds, [math]::Round($len/1MB/$sw.Elapsed.TotalSeconds, 1))
    if ($expectMb -gt 1 -and $len -lt ($expectMb * 0.9 * 1MB)) {
        Write-Output "FAILED $f expected ~$expectMb MB got $([math]::Round($len/1MB,1)) MB"
    }
}
Write-Output 'ALL DONE'
