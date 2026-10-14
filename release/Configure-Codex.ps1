param([switch]$Check,[string]$PythonPath,[string]$ExpectedEpoch,[string]$BridgeConfigPath)
$ErrorActionPreference='Stop'
if($Check) {
    Write-Host '请打开 ChatGPT 客户端 → 设置 → 钩子，信任全部。'
    Write-Host '目视确认本项目五项钩子已出现、已信任且未禁用或报错；此命令不执行自动检查。'
    exit 0
}
function Test-BridgePython([string]$Interpreter,[string]$Code) {
    try {
        & $Interpreter -c $Code 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function Find-BridgePython {
    $candidates=@()
    if($PythonPath){$candidates+=([IO.Path]::GetFullPath($PythonPath))}else{
        $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
        if($launcher){try{$resolved=& $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null;if($LASTEXITCODE -eq 0 -and $resolved){$candidates+=([string]$resolved).Trim()}}catch{Write-Host 'Python launcher has no usable interpreter; checking existing installations.'}}
        $installed=Get-Command python.exe -ErrorAction SilentlyContinue
        if($installed){$candidates+=$installed.Source}
        foreach($base in @((Join-Path $env:LOCALAPPDATA 'Programs/Python'),$env:ProgramFiles)){
            if(Test-Path -LiteralPath $base){$candidates+=Get-ChildItem -LiteralPath $base -Directory -Filter 'Python*' | ForEach-Object {Join-Path $_.FullName 'python.exe'}}
        }
    }
    foreach($candidate in ($candidates | Select-Object -Unique)) {
        if(-not (Test-Path -LiteralPath $candidate -PathType Leaf)){Write-Host "Missing interpreter: $candidate";continue}
        if(-not $PythonPath -and $candidate -like '*\AppData\Local\Microsoft\WindowsApps\*'){Write-Host "Store alias skipped: $candidate (use -PythonPath for the real executable)";continue}
        if(-not (Test-BridgePython $candidate 'import sys; assert sys.version_info >= (3,10); import tkinter, _tkinter')){Write-Host "Python 3.10+ with tkinter/_tkinter required: $candidate";if($PythonPath){throw '所选 Python 必须为 3.10 或更新且包含 tkinter/_tkinter；请自行补齐。本工具不安装或升级 Python。'};continue}
        if(Test-BridgePython $candidate 'import tkinter; r=tkinter.Tk(); r.withdraw(); r.update_idletasks(); r.destroy()'){Write-Host "Python/Tk window verified: $candidate";return $candidate}
        if(-not (Test-BridgePython $candidate "import _tkinter; assert _tkinter.TCL_VERSION == '8.6' and _tkinter.TK_VERSION == '8.6'")){throw '当前 Python 的 Tk 组件无法运行且不兼容随包 Tcl/Tk 8.6；请自行修复 Python 的 Tcl/Tk 组件。'}
        $tclRoot=Install-BundledTclTk
        $env:TCL_LIBRARY=Join-Path $tclRoot 'tcl/tcl8.6'
        $env:TK_LIBRARY=Join-Path $tclRoot 'tcl/tk8.6'
        if(-not (Test-BridgePython $candidate 'import tkinter; r=tkinter.Tk(); r.withdraw(); r.update_idletasks(); r.destroy()')){throw '随包 Tcl/Tk 配置后仍不能显示窗口；请自行修复现有 Python。钩子未更改。'}
        $script:TclLibraries=@{tclLibrary=$env:TCL_LIBRARY;tkLibrary=$env:TK_LIBRARY}
        Write-Host "Existing Python and bundled Tcl/Tk verified: $candidate"
        return $candidate
    }
    throw '未找到 Python 3.10+ 和 tkinter/_tkinter。请自行安装或修复 Python 后重试；本工具未安装或升级 Python，钩子未更改。'
}
function Install-BundledTclTk {
    $runtimeArchive=Join-Path $PSScriptRoot 'tcl-tk.zip'
    if(-not (Test-Path -LiteralPath $runtimeArchive)){throw 'Missing bundled Tcl/Tk. Reimport the complete plugin package.'}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $runtimeZip=[IO.Compression.ZipFile]::OpenRead($runtimeArchive)
    try {
        foreach($entry in $runtimeZip.Entries){
            if([IO.Path]::IsPathRooted($entry.FullName) -or $entry.FullName -match '(^|[\\/])\.\.([\\/]|$)'){throw 'Invalid runtime archive path.'}
        }
        foreach($name in @('tcl/tcl8.6/init.tcl','tcl/tk8.6/tk.tcl','runtime-manifest.json')){
            if(-not $runtimeZip.GetEntry($name)){throw "Incomplete bundled runtime: $name"}
        }
    } finally {$runtimeZip.Dispose()}
    $runtimeId=(Get-FileHash -LiteralPath $runtimeArchive -Algorithm SHA256).Hash.ToLower()
    $runtimeBase=Join-Path $env:LOCALAPPDATA 'CodexBandBridge/tcl-tk'
    $runtime=Join-Path $runtimeBase $runtimeId
    if(-not (Test-Path -LiteralPath $runtime)){
        $runtimeStage=Join-Path $runtimeBase ('staging-'+[guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $runtimeStage -Force | Out-Null
        Expand-Archive -LiteralPath $runtimeArchive -DestinationPath $runtimeStage
        $runtimeBaseFull=[IO.Path]::GetFullPath($runtimeBase).TrimEnd('\')+'\'
        foreach($runtimePath in @($runtimeStage,$runtime)){
            if(-not ([IO.Path]::GetFullPath($runtimePath).StartsWith($runtimeBaseFull,[StringComparison]::OrdinalIgnoreCase))){throw 'Runtime move target is outside the tool directory.'}
        }
        Move-Item -LiteralPath $runtimeStage -Destination $runtime
    }
    return $runtime
}
$sourceConfig=if($BridgeConfigPath){$BridgeConfigPath}else{Join-Path $PSScriptRoot 'bridge-client.json'}
if(-not (Test-Path -LiteralPath $sourceConfig)){throw 'Open this AstroBox plugin before installing Hooks. No files were replaced.'}
$client=Get-Content -LiteralPath $sourceConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if($ExpectedEpoch -and $client.setupEpoch -ne $ExpectedEpoch){throw 'Command belongs to a different plugin instance. Copy it again.'}
if($client.endpoint -notmatch '^http://127\.0\.0\.1:\d+$' -or $client.token.Length -lt 32 -or $client.deliveryMode -ne 'launch'){throw 'Invalid local bridge configuration. No files were replaced.'}
$python=Find-BridgePython
$targetRoot=Join-Path $env:LOCALAPPDATA 'CodexBandBridge'
$currentFile=Join-Path $targetRoot 'current.json'
$archive=Join-Path $PSScriptRoot 'codex-hooks.zip'
if(-not (Test-Path -LiteralPath $archive)){throw 'Missing bundled codex-hooks.zip. Nothing was replaced.'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach($entry in $zip.Entries){
        if([IO.Path]::IsPathRooted($entry.FullName) -or $entry.FullName -match '(^|[\\/])\.\.([\\/]|$)' -or $entry.FullName -match '(^|[\\/])\.local([\\/]|$)'){throw 'Invalid bundled archive path.'}
    }
    foreach($required in @('VERSION','scripts/install_hooks.py','scripts/desktop_doctor.py','codex-hook/bridge_hook.py','codex-hook/command_format.py','codex-hook/stable_entry.py')) {
        if(-not $zip.GetEntry($required)){throw "Incomplete archive: $required"}
    }
} finally {$zip.Dispose()}
$releaseId=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
$release=Join-Path $targetRoot "releases\$releaseId"
$stage=Join-Path $targetRoot ('staging-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $stage
& $python -m compileall -q (Join-Path $stage 'codex-hook') (Join-Path $stage 'scripts')
if($LASTEXITCODE -ne 0){throw 'Staged validation failed. Previous installation is untouched.'}
if(-not (Test-Path -LiteralPath $release)){
    New-Item -ItemType Directory -Path (Split-Path $release) -Force | Out-Null
    Move-Item -LiteralPath $stage -Destination $release
}
$tclConfig=if($script:TclLibraries){$script:TclLibraries}else{@{}}
$tclConfig | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $release 'codex-hook/tcl-runtime.json') -Encoding UTF8
# Owned Hooks switch only after all prechecks; previous releases remain intact.
$stableEntry=Join-Path $targetRoot 'codex_band_hook.py'
$entrySource=Join-Path $release 'codex-hook/stable_entry.py'
if(Test-Path -LiteralPath $stableEntry){
    if((Get-FileHash -LiteralPath $stableEntry).Hash -ne (Get-FileHash -LiteralPath $entrySource).Hash){throw 'Stable launcher differs; previous installation retained. Do not silently replace the trusted entry.'}
}else{Copy-Item -LiteralPath $entrySource -Destination $stableEntry}
$pointer=@{path=$release;sha256=$releaseId;bridgeConfigPath=[IO.Path]::GetFullPath($sourceConfig);pythonPath=$python} | ConvertTo-Json
$pointerTmp=$currentFile+'.tmp'
[IO.File]::WriteAllText($pointerTmp,$pointer,[Text.UTF8Encoding]::new($false))
$configHome=if($env:CODEX_HOME){$env:CODEX_HOME}else{Join-Path $env:USERPROFILE '.codex'}
$hooksFile=Join-Path $configHome 'hooks.json'
$originalHooks=$null
if(Test-Path -LiteralPath $hooksFile){$originalHooks=[IO.File]::ReadAllBytes($hooksFile)}
$switched=$false
try {
    $installOutput=& $python (Join-Path $release 'scripts/install_hooks.py') --bridge-config $sourceConfig --activate-local --stable-entry $stableEntry --stable-pointer $currentFile
    $installExit=$LASTEXITCODE
    $installOutput | ForEach-Object {Write-Host $_}
    if($installExit -ne 0){throw 'Hooks installation failed before activation.'}
    $switched=$true
    if(Test-Path -LiteralPath $currentFile){[IO.File]::Replace($pointerTmp,$currentFile,$currentFile+'.bak')}else{[IO.File]::Move($pointerTmp,$currentFile)}
} catch {
    if($switched){
        if($null -ne $originalHooks){
            $rollback=$hooksFile+'.rollback-tmp';[IO.File]::WriteAllBytes($rollback,$originalHooks)
            [IO.File]::Replace($rollback,$hooksFile,$hooksFile+'.failed-upgrade-backup')
        } else {
            # Preserve the failed attempt for diagnosis; it is no longer active.
            Move-Item -LiteralPath $hooksFile -Destination ($hooksFile+'.failed-upgrade-'+[guid]::NewGuid().ToString('N'))
        }
    }
    throw ('Installation failed; previous Hooks and release pointer were retained or restored. '+$_.Exception.Message)
}
if($installOutput -contains 'HOOK_DEFINITIONS_UNCHANGED'){Write-Host '本次更新钩子定义未变，已信任者无需再次信任。'}else{Write-Host '首次迁移：ChatGPT 客户端 → 设置 → 钩子 → 信任全部。'}
Write-Host '目视确认本项目五项钩子已出现、已信任且未禁用。完成后打开 AstroBox 插件上方“启动 Codex Connector”开关。'
