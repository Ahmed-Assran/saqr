# PowerShell runner for Windows automated daily execution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

$DateTag = (Get-Date).ToString("yyyy-MM-dd")
$LogDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "pipeline_$DateTag.log"

Write-Host "Starting KSA US-Stock Lead Scouter Pipeline for $DateTag..." -ForegroundColor Cyan

# Execute python CLI
python -m src.cli run-all --date $DateTag --limit 50 --resume *>> $LogFile

Write-Host "Pipeline execution completed. Check $LogFile and exports/ directory." -ForegroundColor Green
