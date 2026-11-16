# Hyperthymesia 一键安装（Windows PowerShell）：
#   $env:HY_AGENTS="claude"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
# HY_AGENTS 可写多个（用逗号分隔：claude,codex），可省略；写了就顺带接入这些 agent。
$ErrorActionPreference = 'Stop'
# PyInstaller unpacks before Python starts; test standard Windows TEMP and explain failures here.
$tempProbe = $null
try {
  $tempProbe = [IO.Path]::GetTempFileName()
} catch {
  throw 'TEMP/TMP is not writable or the disk is full. Set TEMP and TMP to a writable drive, reopen the agent, and retry.'
} finally {
  if ($tempProbe -and (Test-Path $tempProbe)) { Remove-Item $tempProbe -Force }
}
$dir = Join-Path $env:USERPROFILE '.hyperthymesia\bin'
$bin = Join-Path $dir 'hyperthymesia.exe'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Write-Host '下载 hyperthymesia-windows-x64.exe ……'
Invoke-WebRequest -UseBasicParsing 'https://github.com/ymdfker/Hyperthymesia/releases/latest/download/hyperthymesia-windows-x64.exe' -OutFile $bin
Unblock-File $bin                                          # 去掉网络下载标记，避免 SmartScreen 拦截
& $bin --version
if ($LASTEXITCODE -ne 0) { throw 'Executable startup failed. Check TEMP/TMP write access and free disk space; installation is not complete.' }
$p = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $p) { $p = '' }
if (-not (($p -split ';') -contains $dir)) { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $dir).TrimStart(';'), 'User') }   # 只改当前用户的 PATH
Write-Host "已安装到 $bin"
if ($env:HY_AGENTS) {
  foreach ($a in $env:HY_AGENTS -split ',') {
    & $bin install $a.Trim()
    if ($LASTEXITCODE -ne 0) { throw ('Agent integration failed: ' + $a) }
  }
  Write-Host '完成：请完全退出并重新打开你的 agent。'
} else { Write-Host "下一步：重开终端后执行 hyperthymesia install claude（换成你用的 agent），然后重启 agent。" }
