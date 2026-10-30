# Isolated experimental identity: never infer it from another installation.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-NipatInstallationProfile($Profile) {
    $expected = [ordered]@{
        schema_version = 1; channel = 'experimental08'; display_name = 'NIPAT Experimental08'
        app_dir_name = 'NIPAT-Experimental08'; data_dir_name = 'NIPAT-Experimental08'
        distro_prefix = 'NIPAT-Experimental08-'; resume_key = 'NIPAT-Experimental08-ResumeSetup'
        mutex_prefix = 'Local\NIPAT-Experimental08-Setup-'; app_id = 'A83D7E42-162C-438A-9B56-17F86C9F0800'
    }
    if ($null -eq $Profile -or @($Profile.PSObject.Properties).Count -ne $expected.Count) {
        throw 'Profilo di installazione NIPAT Experimental08 mancante o non valido.'
    }
    foreach ($name in $expected.Keys) {
        $typeMatches = $false
        if ($null -ne $Profile.PSObject.Properties[$name]) {
            if ($name -ceq 'schema_version') {
                $typeMatches = ($Profile.$name -is [int]) -or ($Profile.$name -is [long])
            } else { $typeMatches = $Profile.$name -is [string] }
        }
        if (-not $typeMatches -or $Profile.$name -cne $expected[$name]) {
            throw "Identita di installazione non supportata: $name. Le altre installazioni non vengono modificate."
        }
    }
}

function Get-NipatInstallationProfile {
    $profile = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install-profile.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-NipatInstallationProfile $profile
    return $profile
}

function Assert-NipatInstallationChannel($Value, [string] $Description) {
    $present = $false
    if ($null -ne $Value) {
        if ($Value -is [Collections.IDictionary]) { $present = $Value.Contains('installation_channel') }
        else { $present = $null -ne $Value.PSObject.Properties['installation_channel'] }
    }
    if (-not $present -or $Value.installation_channel -cne (Get-NipatInstallationProfile).channel) {
        throw "$Description appartiene a un altro canale di installazione. NIPAT Experimental08 non adotta configurazioni di NIPAT Desktop o di altre installazioni."
    }
}

function Assert-NipatRuntimeNamespace([string] $Distro, [string] $RootfsSha256, [string] $RuntimeDirectory = '') {
    $profile = Get-NipatInstallationProfile
    if ($RootfsSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Identita rootfs non valida.' }
    $allowed = @($profile.distro_prefix + $RootfsSha256.Substring(0, 40))
    if ($RuntimeDirectory) { $allowed += Get-NipatRuntimeDistroName $RootfsSha256 $RuntimeDirectory }
    if ($Distro -cnotin $allowed) {
        throw 'La distribuzione richiesta non appartiene a questa installazione NIPAT Experimental08.'
    }
}

function Assert-NipatInstallationLocation([string] $Project) {
    $profile = Get-NipatInstallationProfile
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA non disponibile.' }
    $expected = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $profile.app_dir_name
    if (Test-Path -LiteralPath (Join-Path $Project '.runtime\install-layout.json') -PathType Leaf) {
        Read-NipatInstallLayout $Project | Out-Null
        return
    }
    if ([IO.Path]::GetFullPath($Project).TrimEnd('\') -ine [IO.Path]::GetFullPath($expected).TrimEnd('\')) {
        throw 'NIPAT Experimental08 deve essere installato nella propria cartella dedicata. Avviare il relativo installer normalmente.'
    }
    # Reject junctions/symlinks in existing installation-specific paths before writes.
    $base = Join-Path $env:LOCALAPPDATA $profile.data_dir_name
    $paths = @($Project, $base)
    foreach ($relative in @('.runtime', '.runtime\installer', '.runtime\installer\recovery', '.distribution')) {
        $paths += Join-Path $Project $relative
    }
    foreach ($relative in @('cache', 'wsl', 'wsl\registrations', 'data', 'runs')) {
        $paths += Join-Path $base $relative
    }
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path) {
            if (((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "La cartella dedicata non puo essere un collegamento: $path. Nessun file viene modificato."
            }
        }
    }
}

. (Join-Path $PSScriptRoot 'install-layout.ps1')
