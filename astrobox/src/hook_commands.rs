pub fn script(name:&str,check:bool,epoch:&str)->String {
    format!(r#"& {{
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:APPDATA 'moe.astralsight.astrobox\plugins'
$files = @(Get-ChildItem -LiteralPath $base -Filter '{name}' -Recurse -File | Where-Object {{
  try {{
    $manifest = Get-Content -LiteralPath (Join-Path $_.DirectoryName 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $client = Get-Content -LiteralPath (Join-Path $_.DirectoryName 'bridge-client.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.name -eq 'Codex Band Bridge' -and $manifest.version -eq '{version}' -and $client.setupEpoch -eq '{epoch}'
  }} catch {{ $false }}
}})
if ($files.Count -ne 1) {{ throw 'Current plugin instance not uniquely identified. Copy this command again.' }}
$file = $files[0]
if (-not $file) {{ throw 'Reinstall the AstroBox plugin: bundled script not found.' }}
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $file.FullName -ExpectedEpoch '{epoch}'{}
}}"#,if check{" -Check"}else{""},version=env!("CARGO_PKG_VERSION"))
}
