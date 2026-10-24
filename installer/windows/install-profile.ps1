# Fixed candidate identity: never infer it from a previous stable installation.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-NipatInstallationProfile($Profile) {
    $expected = [ordered]@{
        schema_version = 1; channel = 'preview-0.5'; display_name = 'NIPAT 0.5 Preview'
        app_dir_name = 'NIPAT-0.5-Preview'; data_dir_name = 'NIPAT-0.5-Preview'
        distro_prefix = 'NIPAT-05-Preview-'; resume_key = 'NIPAT-05-Preview-ResumeSetup'
        mutex_prefix = 'Local\NIPAT-05-Preview-Setup-'; app_id = '9E27D451-67B5-4D28-B388-A41CFE2F7D05'
    }
    if ($null -eq $Profile -or @($Profile.PSObject.Properties).Count -ne $expected.Count) {
        throw 'Profilo di installazione NIPAT Preview mancante o non valido.'
    }
    foreach ($name in $expected.Keys) {
        $typeMatches = $false
        if ($null -ne $Profile.PSObject.Properties[$name]) {
            if ($name -ceq 'schema_version') {
                $typeMatches = ($Profile.$name -is [int]) -or ($Profile.$name -is [long])
            } else { $typeMatches = $Profile.$name -is [string] }
        }
        if (-not $typeMatches -or $Profile.$name -cne $expected[$name]) {
            throw "Identita di installazione non supportata: $name. La versione stabile non viene modificata."
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
        throw "$Description appartiene a un altro canale di installazione. NIPAT Preview non adotta configurazioni della versione stabile."
    }
}

function Assert-NipatRuntimeNamespace([string] $Distro, [string] $RootfsSha256) {
    $profile = Get-NipatInstallationProfile
    if ($RootfsSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $Distro -cne ($profile.distro_prefix + $RootfsSha256.Substring(0, 40))) {
        throw 'La distribuzione richiesta non appartiene a questa installazione NIPAT Preview.'
    }
}

function Assert-NipatInstallationLocation([string] $Project) {
    $profile = Get-NipatInstallationProfile
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA non disponibile.' }
    $expected = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $profile.app_dir_name
    if ([IO.Path]::GetFullPath($Project).TrimEnd('\') -ine [IO.Path]::GetFullPath($expected).TrimEnd('\')) {
        throw 'NIPAT Preview deve essere installato nella propria cartella dedicata. Avviare il relativo installer normalmente.'
    }
    # Reject junctions/symlinks in existing candidate-specific paths before writes.
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
