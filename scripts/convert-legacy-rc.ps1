# One-time converter: .rcs/{locale}/resource.rc (numeric IDs) -> languages/{locale}/resource.rc (symbolic IDs)
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent),
    [string[]]$Locales = @('chinese-simplified', 'chinese-traditional')
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Read-IdMaps {
    param([string]$HeaderPath)
    $byValue = @{}
    Get-Content $HeaderPath -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\#define\s+(\w+)\s+(-?\d+)\s*$') {
            $name = $matches[1]
            $val = [int]$matches[2]
            if (-not $byValue.ContainsKey($val)) { $byValue[$val] = [System.Collections.Generic.List[string]]::new() }
            [void]$byValue[$val].Add($name)
        }
    }
    return $byValue
}

function Resolve-Symbol {
    param([int]$Id, [string]$Context, $ByValue)
    if ($Id -eq 1) { return 'IDOK' }
    if ($Id -eq 2) { return 'IDCANCEL' }
    if ($Id -eq -1) { return 'IDC_STATIC' }
    if (-not $ByValue.ContainsKey($Id)) { return [string]$Id }

    $candidates = $ByValue[$Id]
    $pick = {
        param($Pattern)
        foreach ($c in $candidates) { if ($c -match $Pattern) { return $c } }
        return $null
    }

    $symbol = switch ($Context) {
        'menu_resource' { & $pick '^IDR_' }
        'dialog_resource' { & $pick '^IDD_' }
        'menu_command' {
            $s = & $pick '^(SAKURA_|LIST_|MESSENGER_)'
            if ($s) { return $s }
            & $pick '^IDC_'
        }
        'control' { & $pick '^IDC_' }
        default { $null }
    }
    if ($symbol) { return $symbol }
    return $candidates[0]
}

function Get-EnglishHeader {
    param([string]$EnglishRcPath)
    $lines = Get-Content $EnglishRcPath -Encoding UTF8
    $header = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $lines) {
        $header.Add($line)
        if ($line -match '^#endif\s*$' -and ($header -join "`n") -match 'ID_EDIT_REDO') { break }
    }
    return ($header -join "`r`n")
}

function Read-LegacyText {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        return [System.Text.Encoding]::Unicode.GetString($bytes)
    }
    if ($bytes.Length -ge 2 -and $bytes[1] -eq 0x00) {
        return [System.Text.Encoding]::Unicode.GetString($bytes)
    }
    return [System.Text.Encoding]::UTF8.GetString($bytes)
}

function Convert-LegacyBody {
    param([string]$Body, $ByValue)
    $out = [System.Collections.Generic.List[string]]::new()

    foreach ($line in ($Body -split "`r?`n")) {
        $trimmed = $line.Trim()

        if ($trimmed -match '^LANGUAGE\s+LANG_NEUTRAL') { continue }

        if ($trimmed -match '^(\d+)\s+(BITMAP|CURSOR)\s+') {
            $out.Add($line)
            continue
        }

        if ($trimmed -match '^(\d+)\s+(MENU)\s*$') {
            $sym = Resolve-Symbol -Id ([int]$matches[1]) -Context 'menu_resource' -ByValue $ByValue
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}${sym} MENU DISCARDABLE")
            continue
        }

        if ($trimmed -match '^(\d+)\s+(DIALOGEX)\s+(.*)$') {
            $sym = Resolve-Symbol -Id ([int]$matches[1]) -Context 'dialog_resource' -ByValue $ByValue
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}${sym} DIALOGEX $($matches[3])")
            continue
        }

        if ($trimmed -match '^(\d+)\s+(DIALOG)\s+(.*)$') {
            $sym = Resolve-Symbol -Id ([int]$matches[1]) -Context 'dialog_resource' -ByValue $ByValue
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}${sym} DIALOG DISCARDABLE $($matches[3])")
            continue
        }

        if ($trimmed -match '^1\s+VERSIONINFO\s*$') {
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}VS_VERSION_INFO VERSIONINFO")
            continue
        }

        if ($trimmed -eq '{') {
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}BEGIN")
            continue
        }
        if ($trimmed -eq '}') {
            $indent = $line.Substring(0, $line.Length - $trimmed.Length)
            $out.Add("${indent}END")
            continue
        }

        $processed = $line

        if ($processed -match 'MENUITEM') {
            $processed = [regex]::Replace($processed, '(MENUITEM\s+"[^"]*"(?:[^,]*),\s*)(-?\d+)(\s*(?:,\s*\w+)?\s*)$', {
                param($m)
                $sym = Resolve-Symbol -Id ([int]$m.Groups[2].Value) -Context 'menu_command' -ByValue $ByValue
                return $m.Groups[1].Value + $sym + $m.Groups[3].Value
            })
        }

        if ($processed -match '^\s*CONTROL\s+') {
            $processed = [regex]::Replace($processed, '(CONTROL\s+"[^"]*",\s*)(-?\d+)(\s*,)', {
                param($m)
                $sym = Resolve-Symbol -Id ([int]$m.Groups[2].Value) -Context 'control' -ByValue $ByValue
                return $m.Groups[1].Value + $sym + $m.Groups[3].Value
            })
        }

        foreach ($ctlType in @('EDITTEXT', 'LTEXT', 'RTEXT', 'CTEXT', 'PUSHBUTTON', 'DEFPUSHBUTTON', 'COMBOBOX', 'LISTBOX', 'GROUPBOX', 'ICON')) {
            if ($processed -match "^\s*$ctlType\s+") {
                $processed = [regex]::Replace($processed, "($ctlType\s+""[^""]*"",\s*)(-?\d+)(\s*,)", {
                    param($m)
                    $sym = Resolve-Symbol -Id ([int]$m.Groups[2].Value) -Context 'control' -ByValue $ByValue
                    return $m.Groups[1].Value + $sym + $m.Groups[3].Value
                })
            }
        }

        $out.Add($processed)
    }

    return ($out -join "`r`n")
}

$byValue = Read-IdMaps (Join-Path $RepoRoot 'shared\resource_r.h')
$englishHeader = Get-EnglishHeader (Join-Path $RepoRoot 'languages\english\resource.rc')
$englishTail = "`r`n#endif    // neutral resources`r`n/////////////////////////////////////////////////////////////////////////////`r`n"

foreach ($locale in $Locales) {
    $legacyDir = Join-Path $RepoRoot ".rcs\$locale"
    $legacyRc = Join-Path $legacyDir 'resource.rc'
    $outDir = Join-Path $RepoRoot "languages\$locale"
    $outRc = Join-Path $outDir 'resource.rc'

    if (-not (Test-Path $legacyRc)) {
        Write-Warning "Skip $locale : legacy RC not found at $legacyRc"
        continue
    }

    Write-Host "Converting $locale ..."
    $body = Read-LegacyText $legacyRc
    $convertedBody = Convert-LegacyBody -Body $body -ByValue $byValue

    $middle = @"

/////////////////////////////////////////////////////////////////////////////
// neutral resources

#if !defined(AFX_RESOURCE_DLL) || defined(AFX_TARG_NEU)
#ifdef _WIN32
LANGUAGE 0x00, 0x00
#endif //_WIN32

"@

    $content = $englishHeader + $middle + $convertedBody + $englishTail
    [System.IO.File]::WriteAllText($outRc, $content, $Utf8NoBom)

    Get-ChildItem $legacyDir -File | Where-Object { $_.Extension -in '.bmp', '.cur' } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $outDir $_.Name) -Force
    }

    Write-Host "  -> $outRc"
}

Write-Host "Conversion complete."
