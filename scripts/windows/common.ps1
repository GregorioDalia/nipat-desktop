Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NipatProject {
    return (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

function Resolve-NipatDirectory([string] $Directory) {
    # Resolve from the caller's current location without requiring the directory to exist.
    # In particular, do not resolve relative settings against the launcher directory.
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Directory)
}

function Set-NipatEnvironment([string] $Project) {
    # These variables affect this child process only; the system is unchanged.
    $env:NIPAT_PROJECT_DIR = $Project
    $installed = $null
    $backendFile = Join-Path $Project ".runtime\backend.json"
    if (Test-Path -LiteralPath $backendFile -PathType Leaf) {
        $installed = Get-Content -LiteralPath $backendFile -Raw | ConvertFrom-Json
        if ($installed.schema_version -ne 1 -or $installed.backend -ne 'wsl' -or
            $installed.wsl_distro -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or
            $installed.runtime_image -cnotmatch '^sha256:[a-f0-9]{64}$' -or
            -not [IO.Path]::IsPathRooted($installed.data_dir) -or
            -not [IO.Path]::IsPathRooted($installed.runs_dir)) {
            throw "Configurazione dell installer non valida: riaprire 1_SETUP.cmd."
        }
        $env:NIPAT_BACKEND = 'wsl'
        $env:NIPAT_WSL_DISTRO = $installed.wsl_distro
        $env:NIPAT_RUNTIME_IMAGE = $installed.runtime_image
    }
    if ([string]::IsNullOrWhiteSpace($env:NIPAT_WORKSPACE_DIR)) {
        if ($null -ne $installed) {
            $env:NIPAT_WORKSPACE_DIR = Split-Path -Parent $installed.data_dir
        } else {
            $env:NIPAT_WORKSPACE_DIR = Split-Path -Parent $Project
        }
    }
    $env:NIPAT_WORKSPACE_DIR = Resolve-NipatDirectory $env:NIPAT_WORKSPACE_DIR
    if ([string]::IsNullOrWhiteSpace($env:NIPAT_DATA_DIR)) {
        if ($null -ne $installed) { $env:NIPAT_DATA_DIR = $installed.data_dir }
        else { $env:NIPAT_DATA_DIR = Join-Path $env:NIPAT_WORKSPACE_DIR "data" }
    }
    $env:NIPAT_DATA_DIR = Resolve-NipatDirectory $env:NIPAT_DATA_DIR
    if ([string]::IsNullOrWhiteSpace($env:NIPAT_RUNS_DIR)) {
        if ($null -ne $installed) { $env:NIPAT_RUNS_DIR = $installed.runs_dir }
        else { $env:NIPAT_RUNS_DIR = Join-Path $env:NIPAT_WORKSPACE_DIR "runs" }
    }
    $env:NIPAT_RUNS_DIR = Resolve-NipatDirectory $env:NIPAT_RUNS_DIR
    $imageFile = Join-Path $Project ".runtime\runtime-image.txt"
    if ($null -eq $installed -and (Test-Path -LiteralPath $imageFile -PathType Leaf)) {
        $imageId = (Get-Content -LiteralPath $imageFile -Raw).Trim()
        if ($imageId -notmatch '^sha256:[a-f0-9]{64}$') {
            throw "Identificativo runtime non valido. Eseguire nuovamente 1_SETUP.cmd."
        }
        $env:NIPAT_RUNTIME_IMAGE = $imageId
    }
}

function Initialize-NipatWritableDirectory([string] $Directory, [string] $Label) {
    $probe = Join-Path $Directory (".nipat-write-check-" + [Guid]::NewGuid().ToString("N"))
    $stream = $null
    $created = $false
    try {
        [IO.Directory]::CreateDirectory($Directory) | Out-Null
        $stream = [IO.File]::Open($probe, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $created = $true
        $stream.WriteByte(0)
    } catch {
        throw "La cartella $Label non e' scrivibile: $Directory. $($_.Exception.Message)"
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($created) { [IO.File]::Delete($probe) }
    }
}

function Get-NipatPython([string] $Project) {
    return (Join-Path $Project ".runtime\python\python.exe")
}

function Install-NipatPython([string] $Project) {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "Questo pacchetto richiede Windows a 64 bit (x64)."
    }
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    if ($architecture -ne "AMD64") {
        throw "Questo pacchetto supporta Windows x64; architettura rilevata: $architecture."
    }
    $runtime = Join-Path $Project ".runtime"
    $pythonDirectory = Join-Path $runtime "python"
    $python = Get-NipatPython $Project
    $ready = Join-Path $pythonDirectory "nipat-python.ready"
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $ready -PathType Leaf)) {
        $archiveName = "python-3.12.10-embed-amd64.zip"
        $archive = Join-Path $Project ".distribution\$archiveName"
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
            $archive = Join-Path $runtime $archiveName
            if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
                Write-Host "Download di Python portabile 3.12.10 da python.org..."
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                $temporaryArchive = "$archive.download"
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/3.12.10/$archiveName" -OutFile $temporaryArchive
                    $downloadHash = (Get-FileHash -LiteralPath $temporaryArchive -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($downloadHash -ne "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3") {
                        throw "Checksum del download Python non valido."
                    }
                    Move-Item -LiteralPath $temporaryArchive -Destination $archive
                } finally {
                    if (Test-Path -LiteralPath $temporaryArchive) {
                        Remove-Item -LiteralPath $temporaryArchive -Force
                    }
                }
            }
        }
        $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3") {
            throw "Checksum Python non valido: $archive. Nessun file viene eseguito."
        }
        Write-Host "Preparazione di Python locale al progetto..."
        Expand-Archive -LiteralPath $archive -DestinationPath $pythonDirectory -Force
    }
    # Relative paths keep the extracted project movable. No pip, site-packages or venv.
    @("python312.zip", ".", "..\..\src", "..\..") |
        Set-Content -LiteralPath (Join-Path $pythonDirectory "python312._pth") -Encoding ASCII
    & $python -c "import sys; assert sys.version_info[:3] == (3,12,10); import nipat; print('Python locale:', sys.version.split()[0])" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Python portabile non funziona correttamente." }
    "3.12.10" | Set-Content -LiteralPath $ready -Encoding ASCII
    return $python
}

function Assert-NipatDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker non trovato. Installare Docker Desktop, avviarlo e riaprire 1_SETUP.cmd."
    }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose non disponibile in Docker Desktop." }
    $osType = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) {
        throw "Docker non risponde. Avviare Docker Desktop e attendere che il motore sia pronto."
    }
    if (($osType -join "").Trim() -ne "linux") {
        throw "NIPAT richiede il motore Linux di Docker Desktop (Switch to Linux containers)."
    }
}

function Get-NipatImage([string] $Image) {
    # A missing image is expected on first setup; its nonzero exit is handled here.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $json = & docker image inspect $Image 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { return $null }
    $images = @((($json -join "`n") | ConvertFrom-Json))
    if ($images.Count -ne 1) { throw "Risposta inattesa da docker image inspect." }
    return $images[0]
}

function Install-NipatRuntime([string] $Project) {
    $archive = Join-Path $Project ".distribution\runtime.tar"
    $manifest = Join-Path $Project ".distribution\runtime.json"
    if ((Test-Path -LiteralPath $archive) -xor (Test-Path -LiteralPath $manifest)) {
        throw "Pacchetto runtime incompleto: servono runtime.tar e runtime.json insieme."
    }
    if (Test-Path -LiteralPath $archive -PathType Leaf) {
        $metadata = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        if ($metadata.schema_version -ne 1 -or $metadata.image_id -notmatch '^sha256:[a-f0-9]{64}$' -or
            $metadata.archive_sha256 -notmatch '^[a-f0-9]{64}$' -or
            $metadata.os -ne "linux" -or $metadata.architecture -ne "amd64") {
            throw "Manifest del runtime non valido o non compatibile con Windows x64."
        }
        Write-Host "Verifica dell'archivio runtime..."
        $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($archiveHash -ne $metadata.archive_sha256) { throw "Checksum dell'archivio runtime non valido." }
        $image = Get-NipatImage $metadata.image_id
        if ($null -eq $image) {
            Write-Host "Importazione del runtime incluso. Non serve ricompilarlo..."
            & docker image load --input $archive
            if ($LASTEXITCODE -ne 0) { throw "Importazione runtime fallita." }
            $image = Get-NipatImage $metadata.image_id
        }
        if ($null -eq $image -or $image.Id -ne $metadata.image_id) {
            throw "L'immagine importata non corrisponde al manifest."
        }
    } else {
        $candidate = "nipat-scientific-runtime:0.1.0"
        if ($env:NIPAT_RUNTIME_IMAGE) { $candidate = $env:NIPAT_RUNTIME_IMAGE }
        $image = Get-NipatImage $candidate
        if ($null -eq $image) {
            if ($candidate -match '^sha256:') {
                throw "Il runtime precedentemente configurato non e' presente. Ripristinare il pacchetto runtime o rimuovere .runtime\runtime-image.txt per ricostruirlo."
            }
            Write-Host "Costruzione iniziale del runtime (richiede Internet e puo' durare diversi minuti)..."
            $env:NIPAT_RUNTIME_IMAGE = $candidate
            & docker compose -f (Join-Path $Project "compose.yaml") build scientific
            if ($LASTEXITCODE -ne 0) { throw "Costruzione runtime fallita." }
            $image = Get-NipatImage $candidate
        }
    }
    if ($null -eq $image -or $image.Os -ne "linux" -or $image.Architecture -ne "amd64") {
        throw "L'immagine deve essere Linux amd64."
    }
    $env:NIPAT_RUNTIME_IMAGE = $image.Id
    $image.Id | Set-Content -LiteralPath (Join-Path $Project ".runtime\runtime-image.txt") -Encoding ASCII
    Write-Host "Runtime configurato: $($image.Id)"
}
