# Hyperthymesia one-click installer (Windows PowerShell).
# $env:HY_AGENTS="claude"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
# HY_AGENTS accepts comma-separated agent names; omit it to install only the executable.
$ErrorActionPreference = 'Stop'
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
Write-Host 'Downloading hyperthymesia-windows-x64.exe ...'
Invoke-WebRequest -UseBasicParsing 'https://github.com/ymdfker/Hyperthymesia/releases/latest/download/hyperthymesia-windows-x64.exe' -OutFile $bin
Unblock-File $bin
& $bin --version
if ($LASTEXITCODE -ne 0) { throw 'Executable startup failed. Check TEMP/TMP write access and free disk space; installation is not complete.' }
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if (-not (($userPath -split ';') -contains $dir)) {
  [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dir).TrimStart(';'), 'User')
}
Write-Host "Installed at $bin"
if ($env:HY_AGENTS) {
  foreach ($agentName in $env:HY_AGENTS -split ',') {
    $agentName = $agentName.Trim()
    if (-not $agentName) { continue }
    & $bin install $agentName
    if ($LASTEXITCODE -ne 0) { throw ('Agent integration failed: ' + $agentName) }
  }
  Write-Host 'Complete: fully quit and restart your agent.'
} else {
  Write-Host 'Next: reopen your terminal, run hyperthymesia install <agent>, then restart the agent.'
}
