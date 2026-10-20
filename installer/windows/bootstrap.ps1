param(
    [string] $AssetDirectory = '',
    [switch] $Resume
)

. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $project 'scripts\windows\common.ps1')
$transcriptStarted = $false
$mutex = $null
$lockHeld = $false
$result = 1
$state = $null
$statePath = Join-Path $project '.runtime\installer\state.json'
$script:NipatWsl = Join-Path $env:WINDIR 'System32\wsl.exe'
$distro = 'NIPAT-Runtime'

function Save-NipatPhase([string] $Phase) {
    $script:state.phase = $Phase
    $script:state.updated_utc = [DateTime]::UtcNow.ToString('o')
    Write-NipatJsonAtomic $script:statePath $script:state
    Write-Host "NIPAT: $Phase"
}

function Request-NipatReboot {
    Save-NipatPhase 'awaiting_reboot'
    $automaticResume = Register-NipatResume $script:project
    Write-Host 'WSL richiede un riavvio di Windows. Salva il lavoro e riavvia quando preferisci.'
    if ($automaticResume) {
        Write-Host 'La preparazione riprendera al prossimo accesso; puoi anche aprire NIPAT - completa preparazione dal menu Start.'
    } else {
        Write-Host 'Per riprendere dopo il riavvio, aprire NIPAT - completa preparazione dal menu Start.'
    }
}

try {
    Assert-NipatWindowsUser
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutex = New-Object Threading.Mutex($false, ('Local\NIPAT-Setup-' + $sid))
    try { $lockHeld = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $lockHeld = $true }
    if (-not $lockHeld) { throw 'Un altra preparazione NIPAT e gia in corso. Attendere che termini.' }
    Initialize-NipatWritableDirectory (Split-Path -Parent $statePath) 'dello stato installer'
    Start-Transcript -Path (Join-Path $project '.runtime\installer\setup.log') -Append | Out-Null
    $transcriptStarted = $true
    $manifest = Read-NipatInstallerManifest (Join-Path $project '.distribution\installer-manifest.json')
    $previous = $null
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($previous.schema_version -ne 1) { throw 'Stato installer non riconosciuto. Conservare il log e contattare il supporto.' }
        if (-not $AssetDirectory -and $previous.PSObject.Properties['asset_directory']) { $AssetDirectory = $previous.asset_directory }
    }
    if ($AssetDirectory) { $AssetDirectory = Resolve-NipatDirectory $AssetDirectory }
    $state = [ordered]@{
        schema_version = 1; version = $manifest.version; release_tag = $manifest.release_tag
        source_commit = $manifest.source_commit; runtime_image = $manifest.runtime_image
        phase = 'starting'; updated_utc = [DateTime]::UtcNow.ToString('o')
        asset_directory = $AssetDirectory; last_error = $null
    }
    Save-NipatPhase 'checking_windows'
    $base = Join-Path $env:LOCALAPPDATA 'NIPAT'
    $cache = Join-Path $base 'cache'
    $wslDirectory = Join-Path $base 'wsl'
    $distroDirectory = Join-Path $wslDirectory $distro
    $ownershipPath = Join-Path $wslDirectory 'ownership.json'
    Initialize-NipatWritableDirectory $cache 'della cache installer'
    Initialize-NipatWritableDirectory $wslDirectory 'della distribuzione Linux'
    $ready = $false
    if (Test-Path -LiteralPath $script:NipatWsl -PathType Leaf) {
        $version = Invoke-NipatWsl @('--version') -AllowFailure -TimeoutSeconds 30
        $status = Invoke-NipatWsl @('--status') -AllowFailure -TimeoutSeconds 30
        $ready = ($version.ExitCode -eq 0 -and $status.ExitCode -eq 0 -and $null -ne (Get-Service -Name vmcompute -ErrorAction SilentlyContinue))
    }
    if (-not $ready) {
        $computer = Get-CimInstance -ClassName Win32_ComputerSystem
        $processors = @(Get-CimInstance -ClassName Win32_Processor)
        if (-not $computer.HypervisorPresent -and
            @($processors | Where-Object { $_.VirtualizationFirmwareEnabled -eq $false }).Count -gt 0) {
            throw 'La virtualizzazione hardware risulta disabilitata. Abilitarla nel BIOS/UEFI o chiedere al reparto IT di abilitarla nella macchina virtuale, quindi riaprire il setup.'
        }
        Save-NipatPhase 'enabling_wsl'
        Write-Host 'Windows richiedera UAC per abilitare WSL2. Il componente elevato non importa distribuzioni e non esegue analisi.'
        $helper = Join-Path $PSScriptRoot 'EnableWsl.exe'
        if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Componente prerequisiti assente: reinstallare usando NIPAT-Setup.exe.' }
        $process = Start-Process -FilePath $helper -Verb RunAs -Wait -PassThru
        if ($process.ExitCode -in @(3010, 1641)) {
            Request-NipatReboot
            $result = 3010
        } elseif ($process.ExitCode -ne 0) {
            throw "Attivazione WSL non completata (codice $($process.ExitCode)). Verificare autorizzazioni/policy aziendali con il reparto IT e riprovare."
        } else {
            $version = Invoke-NipatWsl @('--version') -AllowFailure -TimeoutSeconds 30
            $status = Invoke-NipatWsl @('--status') -AllowFailure -TimeoutSeconds 30
            $ready = ($version.ExitCode -eq 0 -and $status.ExitCode -eq 0 -and $null -ne (Get-Service -Name vmcompute -ErrorAction SilentlyContinue))
            if (-not $ready) {
                if ($Resume) { throw "WSL non e pronto anche dopo la ripresa. Verificare virtualizzazione e policy con il reparto IT. $($status.Text)" }
                Request-NipatReboot
                $result = 3010
            }
        }
    }
    if ($ready) {
        Save-NipatPhase 'preparing_runtime'
        $names = @(Get-NipatWslNames)
        $registered = $names -contains $distro
        $ownership = $null
        if (Test-Path -LiteralPath $ownershipPath -PathType Leaf) {
            $ownership = Get-Content -LiteralPath $ownershipPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($ownership.schema_version -ne 1 -or $ownership.distro -ne $distro -or
                $ownership.owner_id -cnotmatch '^[a-f0-9]{32}$' -or
                $ownership.rootfs_sha256 -cne $manifest.assets.rootfs.sha256 -or
                $ownership.status -notin @('importing', 'owned')) {
                throw 'La distribuzione NIPAT esistente usa un rootfs o uno stato differente. Nessuna sostituzione automatica viene eseguita: contattare il supporto per la migrazione.'
            }
        }
        if ($registered -and $null -eq $ownership) {
            throw 'Esiste gia NIPAT-Runtime senza il marcatore di proprieta di questa installazione. NIPAT non modifica distribuzioni preesistenti; contattare il supporto.'
        }
        if (-not $registered) {
            if ((Test-Path -LiteralPath $distroDirectory) -and @(Get-ChildItem -LiteralPath $distroDirectory -Force).Count -gt 0) {
                throw "La cartella $distroDirectory contiene gia file ma la distribuzione non risulta registrata. Nessun file viene sovrascritto: contattare il supporto."
            }
            $rootfs = Get-NipatAsset $manifest.assets.rootfs $cache $AssetDirectory
            $ownership = [pscustomobject]@{
                schema_version = 1; distro = $distro; owner_id = [Guid]::NewGuid().ToString('N')
                rootfs_sha256 = $manifest.assets.rootfs.sha256; status = 'importing'
            }
            Write-NipatJsonAtomic $ownershipPath $ownership
            Save-NipatPhase 'importing_distribution'
            Invoke-NipatWsl @('--import', $distro, $distroDirectory, $rootfs, '--version', '2') | Out-Null
        }
        Assert-NipatDistroLocation $distro $distroDirectory
        $product = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/bin/cat', '/etc/nipat-runtime-id')
        if ($product.Text -cne 'nipat-runtime-v1') { throw 'Il contenuto della distribuzione non e un runtime NIPAT riconosciuto.' }
        $owner = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/bin/cat', '/var/lib/nipat/owner-id') -AllowFailure
        if ($owner.ExitCode -ne 0 -and $ownership.status -eq 'importing') {
            Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/bin/install', '-d', '-m', '0700', '/var/lib/nipat') | Out-Null
            $ownership.owner_id | & $script:NipatWsl --distribution $distro --user root --exec /usr/bin/tee /var/lib/nipat/owner-id | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Impossibile registrare la proprieta della distribuzione.' }
            $owner = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/bin/cat', '/var/lib/nipat/owner-id')
        }
        if ($owner.ExitCode -ne 0 -or $owner.Text -cne $ownership.owner_id) {
            throw 'Il marcatore di proprieta della distribuzione non corrisponde. Nessuna modifica viene applicata: contattare il supporto.'
        }
        $ownership.status = 'owned'
        Write-NipatJsonAtomic $ownershipPath $ownership
        Save-NipatPhase 'loading_scientific_image'
        Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/local/bin/nipat-engine', 'ensure') -TimeoutSeconds 240 | Out-Null
        $inspection = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', 'docker', 'image', 'inspect', '--format', '{{.Id}} {{.Os}} {{.Architecture}}', $manifest.runtime_image) -AllowFailure
        if ($inspection.ExitCode -ne 0) {
            $imageArchive = Get-NipatAsset $manifest.assets.scientific_image $cache $AssetDirectory
            $linuxArchive = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', 'wslpath', '-a', '-u', $imageArchive)
            Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', 'docker', 'image', 'load', '--input', $linuxArchive.Text) -TimeoutSeconds 3600 | Out-Null
            $inspection = Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', 'docker', 'image', 'inspect', '--format', '{{.Id}} {{.Os}} {{.Architecture}}', $manifest.runtime_image)
        }
        if ($inspection.Text -cne ($manifest.runtime_image + ' linux amd64')) {
            throw 'L immagine scientifica non corrisponde all identificativo Linux amd64 del manifest.'
        }
        $configuration = [ordered]@{
            schema_version = 1; backend = 'wsl'; wsl_distro = $distro
            runtime_image = $manifest.runtime_image; data_dir = (Join-Path $base 'data'); runs_dir = (Join-Path $base 'runs')
            release_tag = $manifest.release_tag; source_commit = $manifest.source_commit
        }
        Write-NipatJsonAtomic (Join-Path $project '.runtime\backend.json') $configuration
        $manifest.runtime_image | Set-Content -LiteralPath (Join-Path $project '.runtime\runtime-image.txt') -Encoding ASCII
        Set-NipatEnvironment $project
        if (-not (Test-Path -LiteralPath $env:NIPAT_DATA_DIR -PathType Container)) {
            [IO.Directory]::CreateDirectory($env:NIPAT_DATA_DIR) | Out-Null
        }
        Initialize-NipatWritableDirectory $env:NIPAT_RUNS_DIR 'dei risultati'
        $python = Install-NipatPython $project
        Save-NipatPhase 'verifying_installation'
        & $python -m nipat doctor --runtime
        if ($LASTEXITCODE -ne 0) { throw 'Controllo runtime non superato. Consultare setup.log e riprovare dal menu Start.' }
        & $python -m nipat self-test
        if ($LASTEXITCODE -ne 0) { throw "Autotest non superati. Consultare setup.log e i risultati in $env:NIPAT_RUNS_DIR; riaprire il setup dopo la correzione." }
        Save-NipatPhase 'ready'
        Unregister-NipatResume
        Write-Host 'NIPAT e pronto. Apri NIPAT dal menu Start per scegliere un analisi.'
        Write-Host "Dati: $env:NIPAT_DATA_DIR"
        Write-Host "Risultati: $env:NIPAT_RUNS_DIR"
        $result = 0
    }
} catch {
    $message = $_.Exception.Message
    Write-Host ("ERRORE: " + $message) -ForegroundColor Red
    if ($null -ne $state -and $lockHeld) {
        $state.last_error = $message
        try { Save-NipatPhase 'failed' } catch { Write-Host 'Impossibile aggiornare lo stato installer.' }
    }
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($lockHeld) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
exit $result
