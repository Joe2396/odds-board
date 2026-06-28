param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"

$Root = "C:\Users\joete\odds-board"

if (-not (Test-Path -LiteralPath $Root)) {
    throw "Repo not found: $Root"
}

$ScriptsDir = Join-Path $Root "scripts\Football"
$DataDir = Join-Path $Root "football\data"
$DebugDir = Join-Path $Root "football\debug"
$ReportArchive = Join-Path $DebugDir "production_reports"

$PreserveExact = @(
    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_moneylines.py"),
    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_props.py"),
    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_match_stats.py"),
    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_cards_corners.py"),

    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_props_PRE_V23_BACKUP.py"),
    (Join-Path $ScriptsDir "fetch_williamhill_worldcup_match_stats_PRE_PRODUCTION_V4_BACKUP.py"),

    (Join-Path $DataDir "williamhill_worldcup_moneylines.json"),
    (Join-Path $DataDir "williamhill_worldcup_props.json"),
    (Join-Path $DataDir "williamhill_worldcup_match_stats.json"),

    (Join-Path $DebugDir "williamhill_worldcup_match_stats_PRODUCTION_V4"),
    $ReportArchive
)

$PreserveSet = @{}
foreach ($Path in $PreserveExact) {
    $PreserveSet[[System.IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()] = $true
}

function Test-Preserved {
    param([string]$Path)

    $Full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()
    return $PreserveSet.ContainsKey($Full)
}

function Get-ItemBytes {
    param([System.IO.FileSystemInfo]$Item)

    if ($Item -is [System.IO.FileInfo]) {
        return [int64]$Item.Length
    }

    $Measure = Get-ChildItem `
        -LiteralPath $Item.FullName `
        -File `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum

    if ($null -eq $Measure.Sum) {
        return [int64]0
    }

    return [int64]$Measure.Sum
}

function Format-Bytes {
    param([int64]$Bytes)

    if ($Bytes -ge 1TB) {
        return "{0:N2} TB" -f ($Bytes / 1TB)
    }
    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }

    return "$Bytes bytes"
}

$Candidates = @{}

function Add-Candidate {
    param([System.IO.FileSystemInfo]$Item)

    if ($null -eq $Item) {
        return
    }

    if (Test-Preserved -Path $Item.FullName) {
        return
    }

    $Key = [System.IO.Path]::GetFullPath($Item.FullName).TrimEnd('\').ToLowerInvariant()
    $Candidates[$Key] = $Item
}

$ReportSources = @(
    (Join-Path $DebugDir "williamhill_worldcup_props_V23_STAGING\production_validation_report.json"),
    (Join-Path $DebugDir "williamhill_worldcup_match_stats_PRODUCTION_V4\production_validation_report.json")
)

if ($Execute) {
    New-Item -ItemType Directory -Force -Path $ReportArchive | Out-Null

    foreach ($Source in $ReportSources) {
        if (Test-Path -LiteralPath $Source) {
            $ParentName = Split-Path (Split-Path $Source -Parent) -Leaf
            $Destination = Join-Path $ReportArchive ($ParentName + "_validation_report.json")
            Copy-Item -LiteralPath $Source -Destination $Destination -Force
        }
    }
}

if (Test-Path -LiteralPath $ScriptsDir) {
    Get-ChildItem -LiteralPath $ScriptsDir -File -Filter "*.py" |
        Where-Object {
            $_.Name -like "fetch_williamhill_worldcup_props_*.py" -or
            $_.Name -like "fetch_williamhill_worldcup_match_stats_*.py"
        } |
        ForEach-Object {
            Add-Candidate -Item $_
        }
}

if (Test-Path -LiteralPath $DataDir) {
    Get-ChildItem -LiteralPath $DataDir -File -Filter "*.json" |
        Where-Object {
            $_.Name -like "williamhill_worldcup_props_*.json" -or
            $_.Name -like "williamhill_worldcup_match_stats_*.json"
        } |
        ForEach-Object {
            Add-Candidate -Item $_
        }
}

if (Test-Path -LiteralPath $DebugDir) {
    Get-ChildItem -LiteralPath $DebugDir -Directory |
        Where-Object {
            $_.Name -like "williamhill_worldcup_props*" -or
            (
                $_.Name -like "williamhill_worldcup_match_stats*" -and
                $_.Name -ne "williamhill_worldcup_match_stats_PRODUCTION_V4"
            )
        } |
        ForEach-Object {
            Add-Candidate -Item $_
        }
}

$Rows = @()

foreach ($Item in $Candidates.Values) {
    $Bytes = Get-ItemBytes -Item $Item
    $Rows += [PSCustomObject]@{
        Type = if ($Item.PSIsContainer) { "DIR" } else { "FILE" }
        SizeBytes = $Bytes
        Size = Format-Bytes -Bytes $Bytes
        Path = $Item.FullName
    }
}

$Rows = $Rows | Sort-Object SizeBytes -Descending
$TotalBytes = [int64](($Rows | Measure-Object -Property SizeBytes -Sum).Sum)

Write-Host ""
Write-Host "============================================================"
Write-Host "William Hill cleanup"
Write-Host "Mode: $(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' })"
Write-Host "============================================================"
Write-Host ""

if (-not $Rows -or $Rows.Count -eq 0) {
    Write-Host "No obsolete William Hill test files/debug folders found."
    exit 0
}

$Rows |
    Select-Object Type, Size, Path |
    Format-Table -AutoSize

Write-Host ""
Write-Host ("Candidate total: " + (Format-Bytes -Bytes $TotalBytes))
Write-Host ("Candidate count: " + $Rows.Count)
Write-Host ""

if (-not $Execute) {
    Write-Host "Nothing was deleted."
    Write-Host ""
    Write-Host "Review the list, then run:"
    Write-Host 'powershell -ExecutionPolicy Bypass -File ".\cleanup_williamhill_test_waste.ps1" -Execute'
    exit 0
}

$DeletedBytes = [int64]0
$Failed = @()

foreach ($Row in $Rows) {
    try {
        Remove-Item -LiteralPath $Row.Path -Recurse -Force
        $DeletedBytes += [int64]$Row.SizeBytes
        Write-Host ("Deleted: " + $Row.Path)
    }
    catch {
        $Failed += "$($Row.Path) :: $($_.Exception.Message)"
        Write-Warning ("Could not delete: " + $Row.Path)
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host ("Freed approximately: " + (Format-Bytes -Bytes $DeletedBytes))
Write-Host ("Validation reports archived in: " + $ReportArchive)
Write-Host "Canonical scripts, live JSONs, data backups, and current"
Write-Host "PRODUCTION_V4 match-stats diagnostics were preserved."
Write-Host "============================================================"

if ($Failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Failures:"
    foreach ($Failure in $Failed) {
        Write-Host ("  - " + $Failure)
    }
    exit 1
}
