Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-NipatInstallerManifest([string] $Path) {
    $manifest = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.version -ne '0.3.0a2' -or
        $manifest.release_tag -cne ('v' + $manifest.version) -or
        $manifest.source_commit -cnotmatch '^[a-f0-9]{40}$' -or
        $manifest.runtime_image -cnotmatch '^sha256:[a-f0-9]{64}$') {
        throw 'Manifest installer non valido o di una versione non supportata.'
    }
    foreach ($name in @('rootfs', 'scientific_image')) {
        $asset = $manifest.assets.$name
        if ($asset.file -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz$' -or
            $asset.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            (($asset.size -isnot [int]) -and ($asset.size -isnot [long])) -or $asset.size -le 0) {
            throw "Metadati dell'asset $name non validi."
        }
        $expectedUrl = 'https://github.com/GregorioDalia/nipat-desktop/releases/download/' + $manifest.release_tag + '/' + $asset.file
        if ($asset.url -cne $expectedUrl) {
            throw "URL dell'asset $name non autorizzato: atteso il repository e il tag della release NIPAT."
        }
    }
    if ($manifest.assets.rootfs.file -eq $manifest.assets.scientific_image.file) {
        throw 'I due asset devono avere nomi distinti.'
    }
    return $manifest
}

function Write-NipatJsonAtomic([string] $Path, $Value) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = Join-Path $parent ('.write-' + [Guid]::NewGuid().ToString('N') + '.json')
    try {
        $json = ($Value | ConvertTo-Json -Depth 12) + "`n"
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($Path)) {
            [IO.File]::Replace($temporary, $Path, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $Path)
        }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Test-NipatAsset([string] $Path, $Asset) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $Asset.size) { return $false }
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $Asset.sha256)
}

function Get-NipatAsset($Asset, [string] $CacheDirectory, [string] $AssetDirectory) {
    # The manifest always comes from the installed app. Offline folders supply bytes only.
    $cache = Join-Path $CacheDirectory ($Asset.sha256 + '-' + $Asset.file)
    if (Test-NipatAsset $cache $Asset) { return $cache }
    if ($AssetDirectory) {
        $provided = Join-Path $AssetDirectory $Asset.file
        if (Test-Path -LiteralPath $provided -PathType Leaf) {
            Write-Host "Verifica asset locale: $($Asset.file)"
            if (-not (Test-NipatAsset $provided $Asset)) {
                throw "Dimensione o SHA-256 non corrispondenti per $provided. Scaricare nuovamente l'asset della stessa release."
            }
            # Keep this file outside the app: resuming a setup must not require the installer medium.
            $temporaryCopy = $cache + '.copy-' + [Guid]::NewGuid().ToString('N')
            try {
                Copy-Item -LiteralPath $provided -Destination $temporaryCopy
                if (-not (Test-NipatAsset $temporaryCopy $Asset)) { throw 'Copia asset non integra.' }
                Move-Item -LiteralPath $temporaryCopy -Destination $cache -Force
            } finally {
                if (Test-Path -LiteralPath $temporaryCopy) { Remove-Item -LiteralPath $temporaryCopy -Force }
            }
            return $cache
        }
    }
    Write-Host "Download verificato della release $($Asset.file) (puo' richiedere diversi minuti)..."
    $temporary = $cache + '.download-' + [Guid]::NewGuid().ToString('N')
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $Asset.url -OutFile $temporary -TimeoutSec 3600
        if (-not (Test-NipatAsset $temporary $Asset)) {
            throw "Dimensione o SHA-256 non corrispondenti per $($Asset.file). Nessun contenuto scaricato viene eseguito."
        }
        Move-Item -LiteralPath $temporary -Destination $cache -Force
        return $cache
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Assert-NipatWindowsUser {
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
        throw 'L installer richiede Windows 11 x64 e PowerShell a 64 bit.'
    }
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    if ($architecture -ne 'AMD64') { throw 'Questa versione supporta Windows x64, non ARM64.' }
    $build = [int](Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    $product = (Get-CimInstance -ClassName Win32_OperatingSystem).ProductType
    if ($build -lt 22000 -or $product -ne 1) { throw 'Questa versione richiede Windows 11 x64 (build 22000 o successiva).' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Avviare NIPAT normalmente, senza Esegui come amministratore. Solo l abilitazione WSL richiede UAC; dati e distribuzione devono appartenere all utente normale.'
    }
}

function ConvertTo-NipatNativeArgument([string] $Value) {
    # ProcessStartInfo.ArgumentList is unavailable in Windows PowerShell 5.1.
    # Apply Windows command-line quoting, including trailing backslashes.
    if ($Value -ne '' -and $Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $script:NipatWsl
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NipatNativeArgument $_ }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.Encoding]::UTF8
    $start.StandardErrorEncoding = [Text.Encoding]::UTF8
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        $inputEncoding = New-Object Text.UTF8Encoding($false)
        $restoreConsoleEncoding = $false
        $previousInputEncoding = $null
        try {
            if ($null -ne $start.PSObject.Properties['StandardInputEncoding']) {
                $start.StandardInputEncoding = $inputEncoding
            } else {
                # .NET Framework uses Console.InputEncoding and AutoFlush when creating
                # StandardInput: even Start() can write a BOM to an otherwise empty pipe.
                # Bootstrap is single-threaded; restore the console immediately after Start.
                $previousInputEncoding = [Console]::InputEncoding
                [Console]::InputEncoding = $inputEncoding
                $restoreConsoleEncoding = $true
            }
            if (-not $process.Start()) { throw 'Impossibile avviare wsl.exe.' }
        } finally {
            if ($restoreConsoleEncoding) { [Console]::InputEncoding = $previousInputEncoding }
        }
        # No bytes (including a BOM) and EOF: never wait for an install/OOBE prompt.
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill()
            throw "WSL non risponde entro $TimeoutSeconds secondi. Il setup puo essere ripreso; consultare il log e verificare WSL con il reparto IT."
        }
        $outputText = $stdout.GetAwaiter().GetResult().Replace([string][char]0, '').Trim()
        $errorText = $stderr.GetAwaiter().GetResult().Replace([string][char]0, '').Trim()
        $code = $process.ExitCode
        if ($code -ne 0 -and -not $AllowFailure) {
            throw "WSL non ha completato il comando (codice $code): $outputText $errorText"
        }
        return [pscustomobject]@{ ExitCode = $code; Text = $outputText; ErrorText = $errorText }
    } finally {
        $process.Dispose()
    }
}

function Get-NipatWslNames {
    $result = Invoke-NipatWsl @('--list', '--quiet') -TimeoutSeconds 30
    if (-not $result.Text) { return @() }
    return @($result.Text -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Get-NipatLoadedImageId([string] $Output) {
    # The builder exports ONE image by ID, without tags. Use the receipt from
    # loading that verified archive, never an arbitrary image from docker image ls.
    # Graphdriver IDs are config digests; containerd IDs are manifest/index digests.
    if ($Output -cmatch '(?m)^Error\b') {
        throw "Docker segnala un errore nel caricamento dell immagine: $Output"
    }
    $receipts = @($Output -split '\r?\n' | Where-Object { $_ -cmatch '^Loaded image(?: ID)?:' })
    if ($receipts.Count -ne 1 -or
        $receipts[0] -cnotmatch '^Loaded image ID: (sha256:[a-f0-9]{64})$') {
        throw 'Il caricamento deve restituire un solo ID immutabile. Archivio o risposta Docker non riconosciuti; consultare setup.log.'
    }
    return $Matches[1]
}

function Invoke-NipatRuntimeDocker([string] $Distro, [string[]] $Arguments, [int] $TimeoutSeconds = 120) {
    # Use only the dedicated local daemon, independently of Windows Docker settings.
    $prefix = @('--distribution', $Distro, '--user', 'root', '--exec',
        '/usr/bin/env', '-i', 'HOME=/root', 'LANG=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        'docker', '--host', 'unix:///var/run/docker.sock')
    return (Invoke-NipatWsl ($prefix + $Arguments) -TimeoutSeconds $TimeoutSeconds)
}

function Install-NipatScientificImage($Manifest, [string] $CacheDirectory, [string] $AssetDirectory, [string] $Distro) {
    # Reverify and load on each setup/resume. Ordinary launches use the stored ID.
    # This also recovers an interrupted setup without trusting a stale local mapping.
    $archive = Get-NipatAsset $Manifest.assets.scientific_image $CacheDirectory $AssetDirectory
    $linuxArchive = Invoke-NipatWsl @('--distribution', $Distro, '--user', 'root',
        '--exec', 'wslpath', '-a', '-u', $archive)
    Write-Host 'Caricamento dell archivio scientifico verificato...'
    $loaded = Invoke-NipatRuntimeDocker $Distro @('image', 'load', '--input', $linuxArchive.Text) -TimeoutSeconds 3600
    Write-Host $loaded.Text
    if ($loaded.ErrorText) { Write-Host $loaded.ErrorText }
    $imageId = Get-NipatLoadedImageId $loaded.Text
    $inspection = Invoke-NipatRuntimeDocker $Distro @('image', 'inspect', '--format',
        '{{.Id}} {{.Os}} {{.Architecture}}', $imageId)
    if ($inspection.Text -cne ($imageId + ' linux amd64')) {
        throw 'L immagine appena caricata non corrisponde all ID restituito o alla piattaforma Linux amd64.'
    }
    Write-Host "Immagine della build: $($Manifest.runtime_image)"
    Write-Host "Immagine nel runtime locale: $imageId"
    return $imageId
}

function Assert-NipatRuntimeBinding($Manifest, $State, $Configuration) {
    foreach ($name in @('resolved_runtime_image', 'runtime_archive_sha256', 'wsl_distro', 'rootfs_sha256')) {
        if ($null -eq $State.PSObject.Properties[$name]) {
            throw 'Verifica del runtime da aggiornare: riaprire 1_SETUP.cmd.'
        }
    }
    foreach ($name in @('source_runtime_image', 'runtime_archive_sha256', 'wsl_distro', 'rootfs_sha256')) {
        if ($null -eq $Configuration.PSObject.Properties[$name]) {
            throw 'Configurazione del runtime da aggiornare: riaprire 1_SETUP.cmd.'
        }
    }
    if ($Configuration.wsl_distro -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or
        $State.wsl_distro -cne $Configuration.wsl_distro -or
        $State.rootfs_sha256 -cne $Manifest.assets.rootfs.sha256 -or
        $Configuration.rootfs_sha256 -cne $Manifest.assets.rootfs.sha256 -or
        $Configuration.runtime_image -cnotmatch '^sha256:[a-f0-9]{64}$' -or
        $State.resolved_runtime_image -cne $Configuration.runtime_image -or
        $Configuration.source_runtime_image -cne $Manifest.runtime_image -or
        $State.runtime_image -cne $Manifest.runtime_image -or
        $Configuration.source_commit -cne $Manifest.source_commit -or
        $Configuration.release_tag -cne $Manifest.release_tag -or
        $State.runtime_archive_sha256 -cne $Manifest.assets.scientific_image.sha256 -or
        $Configuration.runtime_archive_sha256 -cne $Manifest.assets.scientific_image.sha256) {
        throw 'Il runtime configurato non corrisponde alla verifica di questa release: riaprire 1_SETUP.cmd.'
    }
}

function Assert-NipatDistroLocation([string] $Distro, [string] $ExpectedDirectory) {
    # WSL registration belongs to HKCU. Match its location before recovering an interrupted import.
    $registrations = @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
        ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
        Where-Object { $_.DistributionName -eq $Distro })
    if ($registrations.Count -ne 1 -or $registrations[0].Version -ne 2) {
        throw "La distribuzione $Distro deve essere WSL2 e appartenere all utente attuale."
    }
    $actual = [string]$registrations[0].BasePath
    if ($actual.StartsWith('\\?\')) { $actual = $actual.Substring(4) }
    if ([IO.Path]::GetFullPath($actual).TrimEnd('\') -ine [IO.Path]::GetFullPath($ExpectedDirectory).TrimEnd('\')) {
        throw "Esiste gia' una distribuzione $Distro registrata altrove. NIPAT non la modifica. Consultare il supporto per risolvere il conflitto di nome."
    }
}

function Register-NipatResume([string] $Project) {
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $bootstrap = Join-Path $Project 'installer\windows\bootstrap.ps1'
    $command = '"' + $powershell + '" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $bootstrap + '" -Resume'
    if ($command.Length -gt 260) {
        Write-Host 'Dopo il riavvio aprire NIPAT - completa preparazione dal menu Start (percorso troppo lungo per RunOnce).'
        return $false
    }
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\RunOnce')
    try { $key.SetValue('NIPAT-ResumeSetup', $command, [Microsoft.Win32.RegistryValueKind]::String) }
    finally { $key.Dispose() }
    return $true
}

function Unregister-NipatResume {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\RunOnce', $true)
    if ($null -ne $key) {
        try { $key.DeleteValue('NIPAT-ResumeSetup', $false) } finally { $key.Dispose() }
    }
}
