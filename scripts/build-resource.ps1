# Build resource.dll for SSP language pack locale folders.
param(
    [string]$Locale = '',
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = 'Stop'

function Find-VcVars32 {
    if ($env:VCVARS32_PATH -and (Test-Path $env:VCVARS32_PATH)) { return $env:VCVARS32_PATH }
    $cmd = Get-Command vcvars32.bat -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if ($installPath) {
            $candidate = Join-Path $installPath 'VC\Auxiliary\Build\vcvars32.bat'
            if (Test-Path $candidate) { return $candidate }
        }
    }

    $roots = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Community",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Professional",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\BuildTools",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\Community"
    )
    foreach ($root in $roots) {
        $candidate = Join-Path $root 'VC\Auxiliary\Build\vcvars32.bat'
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Initialize-VcEnv {
    if (Get-Command rc.exe -ErrorAction SilentlyContinue) { return }
    $vcvars = Find-VcVars32
    if (-not $vcvars) {
        throw 'vcvars32.bat not found. Install Visual C++ Build Tools or set VCVARS32_PATH.'
    }
    cmd /c "`"$vcvars`" && set" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($matches[1])" -Value $matches[2] }
    }
}

function Get-LocaleDirs {
    param([string]$Root, [string]$Filter)
    $localeRoot = Join-Path $Root 'languages'
    if (-not (Test-Path $localeRoot)) { throw "languages/ not found at $localeRoot" }
    $dirs = Get-ChildItem $localeRoot -Directory | Where-Object {
        $descript = Join-Path $_.FullName 'descript.txt'
        $hasDllName = (Test-Path $descript) -and (Select-String -Path $descript -Pattern '^dllname,resource\.dll' -Quiet)
        $hasRc = Test-Path (Join-Path $_.FullName 'resource.rc')
        return ($hasDllName -or $hasRc)
    }
    if ($Filter) {
        $dirs = $dirs | Where-Object { $_.Name -eq $Filter }
        if (-not $dirs) { throw "Locale folder not found: $Filter" }
    }
    return $dirs
}

function Get-LangIdHex {
    param([string]$DescriptPath)
    foreach ($line in Get-Content $DescriptPath) {
        if ($line -match '^id,(\d+)\s*$') {
            $dec = [int]$matches[1]
            return ('0x{0:X}' -f $dec)
        }
    }
    throw "Cannot read id from $DescriptPath"
}

function Build-LocaleResource {
    param([string]$LocaleDir, [string]$LangHex, [string]$IncludeRoot)

    Push-Location $LocaleDir
    try {
        if (-not (Test-Path 'resource.rc')) {
            Write-Warning "Skip $(Split-Path $LocaleDir -Leaf): resource.rc missing"
            return $false
        }

        Write-Host "[build] $(Split-Path $LocaleDir -Leaf) (LCID $LangHex)"

        $resFile = Join-Path $LocaleDir 'resource.res'
        $dllFile = Join-Path $LocaleDir 'resource.dll'
        if (Test-Path $resFile) { Remove-Item $resFile -Force }
        if (Test-Path $dllFile) { Remove-Item $dllFile -Force }

        & rc.exe /l $LangHex /i $IncludeRoot /d NDEBUG /fo $resFile (Join-Path $LocaleDir 'resource.rc')
        if ($LASTEXITCODE -ne 0) { throw "rc.exe failed for $LocaleDir" }

        & link.exe /nologo /dll /pdb:none /machine:I386 /nodefaultlib /out:$dllFile /noentry $resFile
        if ($LASTEXITCODE -ne 0) { throw "link.exe failed for $LocaleDir" }

        Remove-Item $resFile -Force
        Write-Host "  OK -> $dllFile"
        return $true
    }
    finally {
        Pop-Location
    }
}

Initialize-VcEnv
$includeRoot = Join-Path $RepoRoot 'shared'
$localeDirs = Get-LocaleDirs -Root $RepoRoot -Filter $Locale
$failed = 0

foreach ($dir in $localeDirs) {
    $descript = Join-Path $dir.FullName 'descript.txt'
    if (-not (Test-Path $descript)) {
        Write-Warning "Skip $($dir.Name): descript.txt missing"
        continue
    }
    $langHex = Get-LangIdHex $descript
    if (-not (Build-LocaleResource -LocaleDir $dir.FullName -LangHex $langHex -IncludeRoot $includeRoot)) {
        $failed++
    }
}

if ($failed -gt 0) {
    throw "$failed locale(s) failed to build"
}

Write-Host 'All builds succeeded.'
