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
    $installerManifestPath = Join-Path $Project '.distribution\installer-manifest.json'
    $profile = $null
    if (Test-Path -LiteralPath $installerManifestPath -PathType Leaf) {
        . (Join-Path $Project 'installer\windows\bootstrap-common.ps1')
        $installerManifest = Read-NipatInstallerManifest $installerManifestPath
        $profile = Get-NipatInstallationProfile
        if (-not (Test-Path -LiteralPath $backendFile -PathType Leaf)) {
            throw 'Installazione NIPAT Experimental08 da completare: riaprire il setup della stessa versione.'
        }
    } elseif (Test-Path -LiteralPath $backendFile -PathType Leaf) {
        throw 'Configurazione WSL priva del manifest della stessa installazione. Ripristinare il pacchetto NIPAT Experimental08.'
    }
    if (Test-Path -LiteralPath $backendFile -PathType Leaf) {
        $installed = Get-Content -LiteralPath $backendFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (($null -ne $installed.PSObject.Properties['app_dir'] -or
            $null -ne $installed.PSObject.Properties['runtime_dir'] -or
            $null -ne $installed.PSObject.Properties['cache_dir']) -and
            -not (Test-Path -LiteralPath (Join-Path $Project '.runtime\install-layout.json') -PathType Leaf)) {
            throw 'Configurazione delle cartelle mancante: riaprire il setup della stessa versione di NIPAT Experimental08.'
        }
        if ($installed.schema_version -ne 1 -or $installed.backend -ne 'wsl' -or
            $installed.wsl_distro -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or
            $installed.runtime_image -cnotmatch '^sha256:[a-f0-9]{64}$' -or
            -not [IO.Path]::IsPathRooted($installed.data_dir) -or
            -not [IO.Path]::IsPathRooted($installed.runs_dir)) {
            throw 'Configurazione dell installer non valida: riaprire NIPAT Experimental08 - completa preparazione dal menu Start.'
        }
        Assert-NipatInstallationChannel $installed 'configurazione di avvio'
        $runtimeDirectory = ''
        if ($null -ne $installed.PSObject.Properties['runtime_dir']) { $runtimeDirectory = [string]$installed.runtime_dir }
        Assert-NipatRuntimeNamespace $installed.wsl_distro $installerManifest.assets.rootfs.sha256 $runtimeDirectory
        if (Test-Path -LiteralPath (Join-Path $Project '.runtime\install-layout.json') -PathType Leaf) {
            $layout = Read-NipatInstallLayout $Project
            foreach ($name in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
                if ($null -eq $installed.PSObject.Properties[$name] -or
                    [string]::IsNullOrWhiteSpace([string]$installed.$name) -or
                    [IO.Path]::GetFullPath([string]$installed.$name).TrimEnd('\') -ine
                    [IO.Path]::GetFullPath([string]$layout.$name).TrimEnd('\')) {
                    throw 'Le cartelle di avvio non corrispondono alla configurazione verificata. Riaprire il setup per completare la preparazione.'
                }
            }
        }
        # An installed application owns its defaults. An inherited shell may
        # belong to another installation. The application subsequently applies
        # its saved user preferences and explicit CLI flags to data/result paths.
        foreach ($name in @('NIPAT_WORKSPACE_DIR', 'NIPAT_DATA_DIR', 'NIPAT_RUNS_DIR',
            'NIPAT_BACKEND', 'NIPAT_WSL_DISTRO', 'NIPAT_RUNTIME_IMAGE')) {
            Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue
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
    $archiveName = "python-3.12.10-embed-amd64.zip"
    $archive = Join-Path $Project ".distribution\$archiveName"
    # Packaged setup/resume restores Python from its verified embedded archive.
    # Ordinary ready launches never call this function.
    if ((Test-Path -LiteralPath $archive -PathType Leaf) -or
        -not (Test-Path -LiteralPath $python -PathType Leaf) -or
        -not (Test-Path -LiteralPath $ready -PathType Leaf)) {
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

function Assert-NipatWslDevelopmentConfiguration {
    if ($env:NIPAT_BACKEND -cne 'wsl' -or
        [string]::IsNullOrWhiteSpace($env:NIPAT_WSL_DISTRO) -or
        $env:NIPAT_WSL_DISTRO -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or
        $env:NIPAT_RUNTIME_IMAGE -cnotmatch '^sha256:[a-f0-9]{64}$') {
        throw 'Per installare NIPAT usare NIPAT-Setup.exe. La preparazione del sorgente richiede un runtime WSL configurato: NIPAT_BACKEND=wsl, NIPAT_WSL_DISTRO e NIPAT_RUNTIME_IMAGE con ID sha256 completo. Consultare docs/INSTALLATORE_WINDOWS.md.'
    }
}
