param(
    [string] $AssetDirectory = '',
    [switch] $Resume
)

. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
. (Join-Path $PSScriptRoot 'bootstrap-migration.ps1')
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $project 'scripts\windows\common.ps1')
$transcriptStarted = $false
$mutex = $null
$lockHeld = $false
$result = 1
$state = $null
$statePath = Join-Path $project '.runtime\installer\state.json'
$script:NipatWsl = Join-Path $env:WINDIR 'System32\wsl.exe'
$distro = $null

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
        Write-Host ('La preparazione riprendera al prossimo accesso; puoi anche aprire ' + $profile.display_name + ' - completa preparazione dal menu Start.')
    } else {
        Write-Host ('Per riprendere dopo il riavvio, aprire ' + $profile.display_name + ' - completa preparazione dal menu Start.')
    }
}

try {
    Assert-NipatWindowsUser
    Assert-NipatInstallationLocation $project
    $profile = Get-NipatInstallationProfile
    $manifest = Read-NipatInstallerManifest (Join-Path $project '.distribution\installer-manifest.json')
    $base = Join-Path $env:LOCALAPPDATA $profile.data_dir_name
    $dataRoots = Get-NipatPreviousDataRoots $project $base
    # Reject a foreign state before even creating the log or recovery directory.
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Assert-NipatInstallationChannel (Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json) 'Lo stato precedente'
    }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutex = New-Object Threading.Mutex($false, ($profile.mutex_prefix + $sid))
    try { $lockHeld = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $lockHeld = $true }
    if (-not $lockHeld) { throw 'Un altra preparazione NIPAT e gia in corso. Attendere che termini.' }
    Initialize-NipatWritableDirectory (Split-Path -Parent $statePath) 'dello stato installer'
    Start-Transcript -LiteralPath (Join-Path $project '.runtime\installer\setup.log') -Append | Out-Null
    $transcriptStarted = $true
    $recoveryPath = Save-NipatRecoverySnapshot $project $manifest
    $previous = $null
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($previous.schema_version -ne 1) { throw 'Stato installer non riconosciuto. Conservare il log e contattare il supporto.' }
        # A new self-contained setup uses its embedded cache, never a stale path from an older installer.
        if ($Resume -and -not $AssetDirectory -and $previous.PSObject.Properties['asset_directory']) { $AssetDirectory = $previous.asset_directory }
    }
    if ($AssetDirectory) { $AssetDirectory = Resolve-NipatDirectory $AssetDirectory }
    $state = [ordered]@{
        schema_version = 1; installation_channel = $profile.channel; version = $manifest.version; release_tag = $manifest.release_tag
        source_commit = $manifest.source_commit; runtime_image = $manifest.runtime_image
        resolved_runtime_image = $null; runtime_archive_sha256 = $null
        wsl_distro = $null; rootfs_sha256 = $manifest.assets.rootfs.sha256; recovery_snapshot = $recoveryPath
        phase = 'starting'; updated_utc = [DateTime]::UtcNow.ToString('o')
        asset_directory = $AssetDirectory; last_error = $null
    }
    Save-NipatPhase 'checking_windows'
    $cache = Join-Path $base 'cache'
    $wslDirectory = Join-Path $base 'wsl'
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
        $target = Get-NipatRuntimeTarget $wslDirectory $manifest.assets.rootfs.sha256 @(Get-NipatWslNames)
        $distro = $target.Distro
        $state.wsl_distro = $distro
        if (-not $target.Registered) { Save-NipatPhase 'importing_distribution' }
        Initialize-NipatRuntimeTarget $target $manifest.assets.rootfs $cache $AssetDirectory
        Save-NipatPhase 'loading_scientific_image'
        Invoke-NipatWsl @('--distribution', $distro, '--user', 'root', '--exec', '/usr/local/bin/nipat-engine', 'ensure') -TimeoutSeconds 240 | Out-Null
        $runtimeImage = Install-NipatScientificImage $manifest $cache $AssetDirectory $distro
        $state.resolved_runtime_image = $runtimeImage
        $state.runtime_archive_sha256 = $manifest.assets.scientific_image.sha256
        $configuration = [ordered]@{
            schema_version = 1; installation_channel = $profile.channel; backend = 'wsl'; wsl_distro = $distro
            rootfs_sha256 = $manifest.assets.rootfs.sha256
            runtime_image = $runtimeImage; source_runtime_image = $manifest.runtime_image
            runtime_archive_sha256 = $manifest.assets.scientific_image.sha256
            data_dir = $dataRoots.data_dir; runs_dir = $dataRoots.runs_dir
            release_tag = $manifest.release_tag; source_commit = $manifest.source_commit
        }
        if (-not (Test-Path -LiteralPath $configuration.data_dir -PathType Container)) {
            [IO.Directory]::CreateDirectory($configuration.data_dir) | Out-Null
        }
        Initialize-NipatWritableDirectory $configuration.runs_dir 'dei risultati'
        $python = Install-NipatPython $project
        Save-NipatPhase 'verifying_installation'
        Complete-NipatRuntimeActivation $project $statePath $state $configuration {
            & $python -m nipat doctor --runtime
            if ($LASTEXITCODE -ne 0) { throw 'Controllo runtime non superato. Consultare setup.log e riprovare dal menu Start.' }
            & $python -m nipat self-test
            if ($LASTEXITCODE -ne 0) { throw "Autotest non superati. Consultare setup.log e i risultati in $env:NIPAT_RUNS_DIR; riaprire il setup dopo la correzione." }
        }
        Unregister-NipatResume
        Write-Host ($profile.display_name + ' e pronto. Apri ' + $profile.display_name + ' dal menu Start per scegliere un analisi.')
        Write-Host "Dati: $($configuration.data_dir)"
        Write-Host "Risultati: $($configuration.runs_dir)"
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
