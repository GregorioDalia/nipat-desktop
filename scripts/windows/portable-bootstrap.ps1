# Preparation state for the packaged Docker Desktop application. Source checkouts
# keep their explicit setup path; the WSL installer owns its separate state.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NipatPortablePackage([string] $Project) {
    $releasePath = Join-Path $Project 'release.json'
    $packaged = (Test-Path -LiteralPath (Join-Path $Project '.distribution\docker-desktop.json')) -or
        (Test-Path -LiteralPath (Join-Path $Project '.distribution\runtime.json')) -or
        (Test-Path -LiteralPath (Join-Path $Project '.distribution\runtime.tar'))
    if (-not (Test-Path -LiteralPath $releasePath -PathType Leaf)) {
        if ($packaged) { throw 'Pacchetto NIPAT incompleto: manca release.json. Ripristinare la stessa versione.' }
        return $null
    }
    try {
        $release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $release.runtime) {
            if ($packaged) { throw 'Metadati del runtime scientifico mancanti.' }
            return $null
        }
        $runtimePath = Join-Path $Project '.distribution\runtime.json'
        $archive = Join-Path $Project '.distribution\runtime.tar'
        $runtime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $versionText = Get-Content -LiteralPath (Join-Path $Project 'pyproject.toml') -Raw -Encoding UTF8
        $version = [regex]::Match($versionText, '(?m)^version\s*=\s*"(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)"\s*$')
        if ($release.schema_version -ne 1 -or -not $version.Success -or
            $release.package_version -cne $version.Groups[1].Value -or
            $release.source_git.available -ne $true -or $release.source_git.dirty -ne $false -or
            $release.source_git.commit -cnotmatch '^[a-f0-9]{40}$' -or
            $release.python.version -cne '3.12.10' -or $release.python.architecture -cne 'amd64' -or
            $release.python.archive_sha256 -cne '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3' -or
            $runtime.schema_version -ne 1 -or $runtime.os -cne 'linux' -or $runtime.architecture -cne 'amd64' -or
            $runtime.image_id -cnotmatch '^sha256:[a-f0-9]{64}$' -or
            $runtime.archive_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $runtime.source_commit -cne $release.source_git.commit -or
            (($runtime.archive_bytes -isnot [int]) -and ($runtime.archive_bytes -isnot [long])) -or
            $runtime.archive_bytes -le 0) {
            throw 'Versione, provenienza o piattaforma del pacchetto non coerenti.'
        }
        foreach ($field in @('schema_version', 'os', 'architecture', 'image_id', 'archive_sha256', 'archive_bytes', 'source_commit')) {
            if ($release.runtime.$field -cne $runtime.$field) { throw "Manifest runtime non coerenti: $field." }
        }
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or
            (Get-Item -LiteralPath $archive).Length -ne $runtime.archive_bytes -or
            -not (Test-Path -LiteralPath (Join-Path $Project '.distribution\python-3.12.10-embed-amd64.zip') -PathType Leaf)) {
            throw 'Componenti incorporati mancanti o incompleti.'
        }
        return [pscustomobject]@{
            version = $release.package_version
            source_commit = $release.source_git.commit
            release_sha256 = (Get-FileHash -LiteralPath $releasePath -Algorithm SHA256).Hash.ToLowerInvariant()
            runtime_manifest_sha256 = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash.ToLowerInvariant()
            runtime_archive_sha256 = $runtime.archive_sha256
            source_image_id = $runtime.image_id
            python_version = '3.12.10'
        }
    } catch {
        throw "Pacchetto NIPAT incompleto o non coerente. Ripristinare il pacchetto della stessa versione. $($_.Exception.Message)"
    }
}

function Get-NipatPortablePythonIdentity([string] $Project) {
    $directory = Join-Path $Project '.runtime\python'
    $python = Get-NipatPython $Project
    $ready = Join-Path $directory 'nipat-python.ready'
    $configuration = Join-Path $directory 'python312._pth'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
        -not (Test-Path -LiteralPath $ready -PathType Leaf) -or
        -not (Test-Path -LiteralPath $configuration -PathType Leaf) -or
        (Get-Content -LiteralPath $ready -Raw).Trim() -cne '3.12.10') {
        throw 'Python locale non preparato.'
    }
    return [pscustomobject]@{
        python_exe_sha256 = (Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant()
        python_config_sha256 = (Get-FileHash -LiteralPath $configuration -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-NipatPortableLocalImageId([string] $Project) {
    $value = (Get-Content -LiteralPath (Join-Path $Project '.runtime\runtime-image.txt') -Raw).Trim()
    if ($value -cnotmatch '^sha256:[a-f0-9]{64}$') { throw 'Identificativo del runtime locale non valido.' }
    return $value
}

function Test-NipatPortableSetupReady([string] $Project, $Package) {
    if ($null -eq $Package) { return $false }
    $path = Join-Path $Project '.runtime\portable-setup.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    try {
        $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.schema_version -ne 1 -or $state.phase -cne 'ready') { return $false }
        foreach ($field in @('version', 'source_commit', 'release_sha256', 'runtime_manifest_sha256',
            'runtime_archive_sha256', 'source_image_id', 'python_version')) {
            if ($state.$field -cne $Package.$field) { return $false }
        }
        $python = Get-NipatPortablePythonIdentity $Project
        if ($state.python_exe_sha256 -cne $python.python_exe_sha256 -or
            $state.python_config_sha256 -cne $python.python_config_sha256) { return $false }
        $localId = Get-NipatPortableLocalImageId $Project
        if ($state.local_image_id -cne $localId) { return $false }
    } catch { return $false }
    # A stopped daemon is actionable and does not invalidate a successful setup.
    Assert-NipatDocker | Out-Null
    $image = Get-NipatImage $localId
    return ($null -ne $image -and $image.Id -ceq $localId -and $image.Os -ceq 'linux' -and $image.Architecture -ceq 'amd64')
}

function Enter-NipatPortableSetupLock([string] $Project) {
    $directory = Join-Path $Project '.runtime'
    Initialize-NipatWritableDirectory $directory 'della preparazione locale'
    try {
        return [IO.File]::Open((Join-Path $directory 'portable-setup.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        throw 'Un altra preparazione NIPAT e gia in corso. Attendere che termini, poi riaprire NIPAT.exe.'
    }
}

function Write-NipatPortableJsonAtomic([string] $Path, $Value) {
    $temporary = $Path + '.write-' + [Guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 8) + "`n"), (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Complete-NipatPortableSetup([string] $Project, $Package) {
    if ($null -eq $Package) { return }
    $currentPackage = Get-NipatPortablePackage $Project
    foreach ($field in @('version', 'source_commit', 'release_sha256', 'runtime_manifest_sha256',
        'runtime_archive_sha256', 'source_image_id', 'python_version')) {
        if ($null -eq $currentPackage -or $currentPackage.$field -cne $Package.$field) {
            throw 'Il pacchetto e cambiato durante la preparazione. Riaprire NIPAT.exe per riprovare.'
        }
    }
    $python = Get-NipatPortablePythonIdentity $Project
    $localId = Get-NipatPortableLocalImageId $Project
    $image = Get-NipatImage $localId
    if ($null -eq $image -or $image.Id -cne $localId -or $image.Os -cne 'linux' -or $image.Architecture -cne 'amd64') {
        throw 'Il runtime scientifico verificato non e piu disponibile.'
    }
    $state = [ordered]@{ schema_version = 1; phase = 'ready' }
    foreach ($field in @('version', 'source_commit', 'release_sha256', 'runtime_manifest_sha256',
        'runtime_archive_sha256', 'source_image_id', 'python_version')) { $state[$field] = $Package.$field }
    $state['local_image_id'] = $localId
    $state['python_exe_sha256'] = $python.python_exe_sha256
    $state['python_config_sha256'] = $python.python_config_sha256
    $state['completed_utc'] = [DateTime]::UtcNow.ToString('o')
    Write-NipatPortableJsonAtomic (Join-Path $Project '.runtime\portable-setup.json') $state
}

function Invoke-NipatPortableSetupProcess([string] $Project) {
    $powershell = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { throw 'Windows PowerShell non disponibile.' }
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Project 'scripts\windows\setup.ps1') -FromLauncher | Out-Host
    return $LASTEXITCODE
}

function Initialize-NipatPortableLaunch([string] $Project, [string[]] $Arguments) {
    if (Test-Path -LiteralPath (Join-Path $Project '.distribution\installer-manifest.json') -PathType Leaf) { return 0 }
    if ($Arguments -ccontains '--dry-run' -or $Arguments -ccontains '--help' -or
        $Arguments -ccontains '-h' -or $Arguments -ccontains '--version' -or $Arguments.Count -eq 0) { return 0 }
    $package = Get-NipatPortablePackage $Project
    if ($null -eq $package) { return 0 }
    if (Test-NipatPortableSetupReady $Project $package) { return 0 }
    # Only the actual wizard subcommand may trigger preparation: an input or
    # output directory literally named 'wizard' must not be mistaken for it.
    $wizardCommand = $false
    for ($index = 0; $index -lt $Arguments.Count; $index++) {
        $argument = $Arguments[$index]
        if ($argument -ceq '--data-dir' -or $argument -ceq '--runs-dir') { $index++; continue }
        if ($argument -cmatch '^--(?:data|runs)-dir=') { continue }
        $wizardCommand = $argument -ceq 'wizard'
        break
    }
    if (-not $wizardCommand) {
        throw 'Preparazione non completata per questa versione. Aprire NIPAT.exe senza argomenti per completarla automaticamente.'
    }
    Write-Host 'NIPAT - prima preparazione o ripresa della configurazione Docker Desktop.'
    Write-Host 'Attendere i controlli e gli autotest; al termine si aprira il menu.'
    $code = Invoke-NipatPortableSetupProcess $Project
    if ($code -ne 0) {
        $log = Join-Path $Project '.runtime\setup.log'
        Write-Host "Preparazione non completata. Consultare $log, risolvere il problema e riaprire NIPAT.exe."
        return $code
    }
    if (-not (Test-NipatPortableSetupReady $Project $package)) { throw 'Preparazione non verificata: riaprire NIPAT.exe per riprovare.' }
    return 0
}
