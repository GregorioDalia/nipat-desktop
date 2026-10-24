# Helpers for resumable runtime preparation. No distribution is removed or replaced.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-NipatOwnership([string] $Path, [string] $Distro) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $record = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-NipatInstallationChannel $record 'Il registro di proprieta'
    if ($record.schema_version -ne 1 -or $record.distro -cne $Distro -or
        $record.owner_id -cnotmatch '^[a-f0-9]{32}$' -or
        $record.rootfs_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $record.status -notin @('importing', 'owned')) {
        throw "Registro di proprieta non valido: $Path. Nessuna distribuzione viene modificata."
    }
    return $record
}

function Get-NipatRuntimeTarget([string] $WslDirectory, [string] $RootfsSha256, [string[]] $Names) {
    if ($RootfsSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Identita rootfs non valida.' }
    $profile = Get-NipatInstallationProfile
    # Even an identical stable rootfs belongs to another installation channel.
    $distro = $profile.distro_prefix + $RootfsSha256.Substring(0, 40)
    $recordPath = Join-Path (Join-Path $WslDirectory 'registrations') ($distro + '.json')
    $ownership = Read-NipatOwnership $recordPath $distro
    if ($null -ne $ownership -and $ownership.rootfs_sha256 -cne $RootfsSha256) {
        throw 'Conflitto tra nome della distribuzione e identita completa del rootfs. Nessuna sostituzione viene eseguita.'
    }
    $registered = $Names -contains $distro
    if ($registered -and $null -eq $ownership) {
        throw "La distribuzione $distro esiste senza il registro di proprieta NIPAT. Nessuna modifica viene eseguita."
    }
    return [pscustomobject]@{
        Distro = $distro; Directory = (Join-Path $WslDirectory $distro)
        OwnershipPath = $recordPath; Ownership = $ownership
        Registered = $registered; Legacy = $false; RootfsSha256 = $RootfsSha256
    }
}

function Assert-NipatRuntimeOwner($Target, [switch] $AllowInitialize) {
    Assert-NipatDistroLocation $Target.Distro $Target.Directory
    $prefix = @('--distribution', $Target.Distro, '--user', 'root', '--exec')
    $product = Invoke-NipatWsl ($prefix + @('/usr/bin/cat', '/etc/nipat-runtime-id'))
    if ($product.Text -cne 'nipat-runtime-v1') { throw 'Il contenuto della distribuzione non e un runtime NIPAT riconosciuto.' }
    $owner = Invoke-NipatWsl ($prefix + @('/usr/bin/cat', '/var/lib/nipat/owner-id')) -AllowFailure
    if ($owner.ExitCode -ne 0 -and $AllowInitialize -and -not $Target.Legacy -and
        $Target.Ownership.status -ceq 'importing') {
        Invoke-NipatWsl ($prefix + @('/usr/bin/install', '-d', '-m', '0700', '/var/lib/nipat')) | Out-Null
        # Only a validated hexadecimal ownership token crosses this fixed shell script as argv.
        Invoke-NipatWsl ($prefix + @('/bin/sh', '-c', 'printf "%s\n" "$1" > /var/lib/nipat/owner-id',
            'nipat-owner', $Target.Ownership.owner_id)) | Out-Null
        $owner = Invoke-NipatWsl ($prefix + @('/usr/bin/cat', '/var/lib/nipat/owner-id'))
    }
    if ($owner.ExitCode -ne 0 -or $owner.Text -cne $Target.Ownership.owner_id) {
        throw 'Il marcatore di proprieta della distribuzione non corrisponde. Nessuna selezione del runtime viene applicata.'
    }
}

function Initialize-NipatRuntimeTarget($Target, $RootfsAsset, [string] $CacheDirectory, [string] $AssetDirectory) {
    if (-not $Target.Registered) {
        if ((Test-Path -LiteralPath $Target.Directory) -and
            @(Get-ChildItem -LiteralPath $Target.Directory -Force).Count -gt 0) {
            throw "La cartella $($Target.Directory) contiene gia file senza una registrazione WSL. Nessun file viene sovrascritto."
        }
        $rootfs = Get-NipatAsset $RootfsAsset $CacheDirectory $AssetDirectory
        if ($null -eq $Target.Ownership) {
            $Target.Ownership = [pscustomobject]@{
                schema_version = 1; installation_channel = (Get-NipatInstallationProfile).channel; distro = $Target.Distro; owner_id = [Guid]::NewGuid().ToString('N')
                rootfs_sha256 = $Target.RootfsSha256; status = 'importing'
            }
        } elseif ($Target.Ownership.status -ne 'importing') {
            throw 'Una distribuzione precedentemente verificata non risulta piu registrata. Conservare il runtime e contattare il supporto.'
        }
        Write-NipatJsonAtomic $Target.OwnershipPath $Target.Ownership
        Invoke-NipatWsl @('--import', $Target.Distro, $Target.Directory, $rootfs, '--version', '2') | Out-Null
        $Target.Registered = $true
    }
    Assert-NipatRuntimeOwner $Target -AllowInitialize
    if (-not $Target.Legacy -and $Target.Ownership.status -ne 'owned') {
        $Target.Ownership.status = 'owned'
        Write-NipatJsonAtomic $Target.OwnershipPath $Target.Ownership
    }
}

function Save-NipatRecoverySnapshot([string] $Project, $Manifest) {
    foreach ($relative in @('.runtime/installer/state.json', '.runtime/backend.json')) {
        $existing = Join-Path $Project $relative
        if (Test-Path -LiteralPath $existing -PathType Leaf) {
            Assert-NipatInstallationChannel (Get-Content -LiteralPath $existing -Raw -Encoding UTF8 | ConvertFrom-Json) $relative
        }
    }
    $name = $Manifest.source_commit + '-' + $Manifest.assets.rootfs.sha256.Substring(0, 16) + '.json'
    $path = Join-Path (Join-Path $Project '.runtime\installer\recovery') $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $snapshot = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatInstallationChannel $snapshot 'Il registro di recupero'
        if ($snapshot.schema_version -ne 1 -or $snapshot.target_source_commit -cne $Manifest.source_commit -or
            $snapshot.target_rootfs_sha256 -cne $Manifest.assets.rootfs.sha256) {
            throw 'Il registro di recupero esistente non corrisponde alla preparazione richiesta.'
        }
        return $path
    }
    $files = [ordered]@{}
    foreach ($relative in @('.runtime/installer/state.json', '.runtime/backend.json', '.runtime/runtime-image.txt')) {
        $original = Join-Path $Project $relative
        if (Test-Path -LiteralPath $original -PathType Leaf) {
            $files[$relative] = [ordered]@{
                sha256 = (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash.ToLowerInvariant()
                content_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($original))
            }
        }
    }
    Write-NipatJsonAtomic $path ([ordered]@{
        schema_version = 1; installation_channel = (Get-NipatInstallationProfile).channel; target_source_commit = $Manifest.source_commit
        target_rootfs_sha256 = $Manifest.assets.rootfs.sha256
        created_utc = [DateTime]::UtcNow.ToString('o'); previous_files = $files
    })
    return $path
}

function Get-NipatPreviousDataRoots([string] $Project, [string] $BaseDirectory) {
    $path = Join-Path $Project '.runtime\backend.json'
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $configuration = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatInstallationChannel $configuration 'La configurazione precedente'
        $profile = Get-NipatInstallationProfile
        if ($configuration.schema_version -ne 1 -or $configuration.backend -cne 'wsl' -or
            $configuration.wsl_distro -cnotmatch ('^' + [regex]::Escape($profile.distro_prefix) + '[a-f0-9]{40}$') -or
            $configuration.runtime_image -cnotmatch '^sha256:[a-f0-9]{64}$' -or
            [string]::IsNullOrWhiteSpace($configuration.data_dir) -or
            [string]::IsNullOrWhiteSpace($configuration.runs_dir) -or
            -not [IO.Path]::IsPathRooted($configuration.data_dir) -or
            -not [IO.Path]::IsPathRooted($configuration.runs_dir)) {
            throw 'La configurazione precedente non e valida. Conservare backend.json e contattare il supporto.'
        }
        return [pscustomobject]@{ data_dir = $configuration.data_dir; runs_dir = $configuration.runs_dir }
    }
    return [pscustomobject]@{
        data_dir = (Join-Path $BaseDirectory 'data'); runs_dir = (Join-Path $BaseDirectory 'runs')
    }
}

function Complete-NipatRuntimeActivation([string] $Project, [string] $StatePath, $State, $Configuration, [scriptblock] $Verify) {
    Assert-NipatInstallationChannel $State 'Lo stato candidato'
    Assert-NipatInstallationChannel $Configuration 'La configurazione candidata'
    Assert-NipatRuntimeNamespace $Configuration.wsl_distro $Configuration.rootfs_sha256
    Assert-NipatRuntimeNamespace $State.wsl_distro $State.rootfs_sha256
    # Tests run with a candidate environment while backend.json still selects the old runtime.
    # Ready state is the final activation gate; an interrupted commit remains blocked and resumable.
    $candidate = [ordered]@{
        NIPAT_PROJECT_DIR = $Project; NIPAT_BACKEND = 'wsl'; NIPAT_WSL_DISTRO = $Configuration.wsl_distro
        NIPAT_RUNTIME_IMAGE = $Configuration.runtime_image; NIPAT_DATA_DIR = $Configuration.data_dir
        NIPAT_RUNS_DIR = $Configuration.runs_dir; NIPAT_WORKSPACE_DIR = (Split-Path -Parent $Configuration.data_dir)
    }
    $previousEnvironment = @{}
    try {
        foreach ($name in $candidate.Keys) {
            $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $candidate[$name], 'Process')
        }
        & $Verify
        Write-NipatJsonAtomic (Join-Path $Project '.runtime\backend.json') $Configuration
        $Configuration.runtime_image | Set-Content -LiteralPath (Join-Path $Project '.runtime\runtime-image.txt') -Encoding ASCII
        $State.phase = 'ready'
        $State.updated_utc = [DateTime]::UtcNow.ToString('o')
        Write-NipatJsonAtomic $StatePath $State
        Write-Host 'NIPAT: ready'
    } finally {
        foreach ($name in $previousEnvironment.Keys) {
            if ($null -eq $previousEnvironment[$name]) {
                Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue
            } else {
                [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
            }
        }
    }
}
