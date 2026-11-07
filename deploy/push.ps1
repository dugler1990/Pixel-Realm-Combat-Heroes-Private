# Deploy from the laptop to the Linode (PowerShell 5.1). From the repo root:
#   powershell -ExecutionPolicy Bypass -File deploy\push.ps1           # deploy files + game code
#   powershell -ExecutionPolicy Bypass -File deploy\push.ps1 -Assets   # also Graphics, Audio, maps
# Needs the "prch" host in C:\Users\Douglas\.ssh\config. Archives are written to files and
# copied with scp: never pipe binary through PowerShell 5.1, it corrupts it.
param([switch]$Assets)
$ErrorActionPreference = "Stop"

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$tmp = Join-Path $env:TEMP "prch_push"
New-Item -ItemType Directory -Force $tmp | Out-Null
Get-ChildItem $tmp -Filter *.tgz | Remove-Item -Force

Invoke-Native tar @("-czf", "$tmp\deploy.tgz", "--exclude=node_modules", "--exclude=build",
                    "--exclude=.env", "--exclude=local.yml", "-C", "deploy", ".")
Invoke-Native tar @("-czf", "$tmp\code.tgz", "--exclude=__pycache__", "--exclude=sprite_venv",
                    "--exclude=logs", "--exclude=.dev_reload_state.json",
                    "Code", "Server", "requirements.txt")
if ($Assets) {
    # MP_MAPS in Code/level_layouts.py is the only list of multiplayer maps.
    $maps = python -c "import sys; sys.path.insert(0, 'Code'); from level_layouts import MP_MAPS, LEVEL_TO_LAYOUT; print(' '.join(LEVEL_TO_LAYOUT[n][3:] for n in MP_MAPS))"
    if ($LASTEXITCODE -ne 0) { throw "could not read MP_MAPS" }
    $folders = @("Graphics", "Audio") + ($maps.Trim() -split " ")
    Invoke-Native tar (@("-czf", "$tmp\assets.tgz", "--exclude=__pycache__") + $folders)
}

Invoke-Native ssh @("prch", "mkdir -p /opt/prch/incoming")
foreach ($archive in Get-ChildItem $tmp -Filter *.tgz) {
    Write-Host "uploading $($archive.Name) ($([math]::Round($archive.Length / 1MB, 1)) MB)"
    Invoke-Native scp @($archive.FullName, "prch:/opt/prch/incoming/")
}
Invoke-Native ssh @("prch", "cd /opt/prch && tar -xzf incoming/deploy.tgz -C /opt/prch && rm incoming/deploy.tgz && bash remote_deploy.sh")
