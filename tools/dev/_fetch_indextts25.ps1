$ErrorActionPreference = 'Continue'
$dst = 'D:\code\NovelCast\models\IndexTTS-2.5'
$base = 'https://hf-mirror.com/IndexTeam/IndexTTS-2.5/resolve/main'
New-Item -ItemType Directory -Force $dst | Out-Null

$files = @{
    'codec.pth'                              = 607320000
    'config.yaml'                            = 2000
    'feat1.pt'                               = 100000
    'feat2.pt'                               = 400000
    'gpt.pth'                                = 3259500000
    'multilingual_zh_ja_yue_char_del.tiktoken' = 900000
    's2mel.pth'                              = 414900000
    'wav2vec2bert_stats.pt'                  = 1000
    'qwen0.6bemo4-merge/Modelfile'           = 1000
    'qwen0.6bemo4-merge/added_tokens.json'   = 1000
    'qwen0.6bemo4-merge/chat_template.jinja' = 2000
    'qwen0.6bemo4-merge/config.json'         = 3000
    'qwen0.6bemo4-merge/generation_config.json' = 200
    'qwen0.6bemo4-merge/merges.txt'          = 1700000
    'qwen0.6bemo4-merge/model.safetensors'   = 1192200000
    'qwen0.6bemo4-merge/special_tokens_map.json' = 700
    'qwen0.6bemo4-merge/tokenizer.json'      = 11500000
    'qwen0.6bemo4-merge/tokenizer_config.json' = 9000
    'qwen0.6bemo4-merge/vocab.json'          = 2800000
}

foreach ($f in $files.Keys) {
    $out = Join-Path $dst $f
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    $expect = $files[$f]
    if ((Test-Path $out) -and ((Get-Item $out).Length -gt ($expect * 0.97))) {
        Write-Output "skip $f ($([math]::Round((Get-Item $out).Length/1MB,1)) MB)"
        continue
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    curl.exe -sS -L --retry 3 --max-time 3600 -o $out "$base/$f"
    $len = if (Test-Path $out) { (Get-Item $out).Length } else { 0 }
    Write-Output ("done {0} {1} MB in {2:N0}s ({3} KB/s)" -f $f, [math]::Round($len/1MB,1), $sw.Elapsed.TotalSeconds, [math]::Round($len/1KB/$sw.Elapsed.TotalSeconds))
    if ($len -lt ($expect * 0.9)) { Write-Output "FAILED $f expected $([math]::Round($expect/1MB,1)) MB got $([math]::Round($len/1MB,1)) MB" }
}
Write-Output 'ALL DONE'
