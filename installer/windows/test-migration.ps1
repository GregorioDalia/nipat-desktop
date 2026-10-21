# Production migration helpers with a simulated WSL boundary; no network/elevation required.
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
. (Join-Path $PSScriptRoot 'bootstrap-migration.ps1')
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Migration check failed: $Message" }
    $script:checks++
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-migration-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$registrations = @{}
$calls = New-Object 'Collections.Generic.List[object]'
$interruptImport = $false
$testArchive = Join-Path $temporary 'rootfs.tar.gz'
[IO.File]::WriteAllText($testArchive, 'verified fixture')
function Get-NipatAsset($Asset, [string] $CacheDirectory, [string] $AssetDirectory) { return $script:testArchive }
function Assert-NipatDistroLocation([string] $Distro, [string] $ExpectedDirectory) {
    if (-not $script:registrations.ContainsKey($Distro) -or
        $script:registrations[$Distro].directory -cne $ExpectedDirectory) { throw 'Unexpected WSL location.' }
}
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    $script:calls.Add($Arguments)
    if ($Arguments[0] -ceq '--import') {
        if ($script:registrations.ContainsKey($Arguments[1])) { throw 'Duplicate import.' }
        [IO.Directory]::CreateDirectory($Arguments[2]) | Out-Null
        [IO.File]::WriteAllText((Join-Path $Arguments[2] 'ext4.vhdx'), 'fixture disk')
        $script:registrations[$Arguments[1]] = @{ directory = $Arguments[2]; product = 'nipat-runtime-v1'; owner = '' }
        if ($script:interruptImport) { throw 'Simulated interruption after import.' }
        return [pscustomobject]@{ ExitCode = 0; Text = ''; ErrorText = '' }
    }
    if ($Arguments[0] -cne '--distribution' -or -not $script:registrations.ContainsKey($Arguments[1])) {
        throw 'Unexpected WSL operation.'
    }
    $entry = $script:registrations[$Arguments[1]]
    if ($Arguments[5] -ceq '/usr/bin/cat') {
        if ($Arguments[6] -ceq '/etc/nipat-runtime-id') { return [pscustomobject]@{ ExitCode = 0; Text = $entry.product; ErrorText = '' } }
        if ($Arguments[6] -ceq '/var/lib/nipat/owner-id') {
            if (-not $entry.owner) { return [pscustomobject]@{ ExitCode = 1; Text = ''; ErrorText = 'absent' } }
            return [pscustomobject]@{ ExitCode = 0; Text = $entry.owner; ErrorText = '' }
        }
    }
    if ($Arguments[5] -ceq '/usr/bin/install') { return [pscustomobject]@{ ExitCode = 0; Text = ''; ErrorText = '' } }
    if ($Arguments[5] -ceq '/bin/sh' -and $Arguments[8] -ceq 'nipat-owner') {
        $entry.owner = $Arguments[9]
        return [pscustomobject]@{ ExitCode = 0; Text = ''; ErrorText = '' }
    }
    throw 'Unexpected WSL operation; destructive commands are never allowed by this fixture.'
}
function New-Ownership([string] $Distro, [string] $Hash, [string] $Status = 'owned') {
    return [pscustomobject]@{ schema_version = 1; distro = $Distro; owner_id = ('a' * 32); rootfs_sha256 = $Hash; status = $Status }
}
try {
    $hash = 'b' * 64
    $asset = [pscustomobject]@{ sha256 = $hash }
    $wsl = Join-Path $temporary 'wsl'
    [IO.Directory]::CreateDirectory($wsl) | Out-Null
    $target = Get-NipatRuntimeTarget $wsl $hash @()
    Assert-Test ($target.Distro -ceq ('NIPAT-Runtime-' + $hash.Substring(0, 40)) -and $target.Distro.Length -le 64) 'fresh install uses deterministic digest-qualified name'
    Initialize-NipatRuntimeTarget $target $asset '' ''
    Assert-Test ($registrations.Count -eq 1 -and $target.Ownership.status -ceq 'owned') 'fresh import verifies owner before marking owned'
    $receipt = Get-Content -LiteralPath $target.OwnershipPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($receipt.rootfs_sha256 -ceq $hash -and $receipt.owner_id -ceq $registrations[$target.Distro].owner) 'full rootfs identity and random owner persisted'
    $imports = @($calls | Where-Object { $_[0] -ceq '--import' }).Count
    $again = Get-NipatRuntimeTarget $wsl $hash @($registrations.Keys)
    Initialize-NipatRuntimeTarget $again $asset '' ''
    Assert-Test (@($calls | Where-Object { $_[0] -ceq '--import' }).Count -eq $imports) 'same rootfs retry reuses verified distro without another import'

    $legacyPath = Join-Path $wsl 'ownership.json'
    $oldHash = 'c' * 64
    $legacy = New-Ownership 'NIPAT-Runtime' $oldHash
    Write-NipatJsonAtomic $legacyPath $legacy
    $legacyBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath))
    $registrations['NIPAT-Runtime'] = @{ directory = (Join-Path $wsl 'NIPAT-Runtime'); product = 'nipat-runtime-v1'; owner = $legacy.owner_id }
    $calls.Clear()
    $different = Get-NipatRuntimeTarget $wsl ('d' * 64) @($registrations.Keys)
    Initialize-NipatRuntimeTarget $different ([pscustomobject]@{ sha256 = ('d' * 64) }) '' ''
    Assert-Test ($different.Distro -cne 'NIPAT-Runtime' -and $registrations.ContainsKey('NIPAT-Runtime')) 'different legacy rootfs is retained alongside new target'
    Assert-Test ([Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath)) -ceq $legacyBefore) 'legacy ownership bytes remain unchanged'
    Assert-Test (@($calls | Where-Object { $_[0] -ceq '--distribution' -and $_[1] -ceq 'NIPAT-Runtime' }).Count -eq 0) 'migration does not execute commands inside old runtime'
    $sameLegacy = Get-NipatRuntimeTarget $wsl $oldHash @($registrations.Keys)
    Initialize-NipatRuntimeTarget $sameLegacy ([pscustomobject]@{ sha256 = $oldHash }) '' ''
    Assert-Test ($sameLegacy.Legacy -and $sameLegacy.Distro -ceq 'NIPAT-Runtime') 'same-hash legacy runtime is reused after full ownership checks'
    Assert-Test ([Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath)) -ceq $legacyBefore) 'legacy reuse does not rewrite its ownership record'
    $registrations['NIPAT-Runtime'].owner = 'wrong'
    Assert-Rejected { Initialize-NipatRuntimeTarget $sameLegacy $asset '' '' } 'reject legacy owner mismatch even when rootfs hash agrees'
    $registrations['NIPAT-Runtime'].owner = $legacy.owner_id

    $unknownHash = 'e' * 64
    $unknown = Get-NipatRuntimeTarget $wsl $unknownHash @($registrations.Keys)
    $registrations[$unknown.Distro] = @{ directory = $unknown.Directory; product = 'nipat-runtime-v1'; owner = '' }
    Assert-Rejected { Get-NipatRuntimeTarget $wsl $unknownHash @($registrations.Keys) } 'registered target without ownership is rejected'
    $registrations.Remove($unknown.Distro)
    Write-NipatJsonAtomic $unknown.OwnershipPath (New-Ownership $unknown.Distro ($unknownHash.Substring(0, 63) + 'f'))
    Assert-Rejected { Get-NipatRuntimeTarget $wsl $unknownHash @($registrations.Keys) } 'full digest prevents prefix-name collisions'

    $interruptHash = 'f' * 64
    $interrupted = Get-NipatRuntimeTarget $wsl $interruptHash @($registrations.Keys)
    $interruptImport = $true
    Assert-Rejected { Initialize-NipatRuntimeTarget $interrupted ([pscustomobject]@{ sha256 = $interruptHash }) '' '' } 'interrupted import reports failure'
    $interruptImport = $false
    $resume = Get-NipatRuntimeTarget $wsl $interruptHash @($registrations.Keys)
    Assert-Test ($resume.Registered -and $resume.Ownership.status -ceq 'importing') 'resume finds recorded incomplete import'
    Initialize-NipatRuntimeTarget $resume ([pscustomobject]@{ sha256 = $interruptHash }) '' ''
    Assert-Test ($resume.Ownership.status -ceq 'owned') 'resume finishes owner initialization without deleting the disk'
    $originalDirectory = $registrations[$resume.Distro].directory
    $registrations[$resume.Distro].directory = Join-Path $temporary 'foreign'
    Assert-Rejected { Initialize-NipatRuntimeTarget $resume $asset '' '' } 'reject target registered at another location'
    $registrations[$resume.Distro].directory = $originalDirectory
    $registrations[$resume.Distro].product = 'foreign-product'
    Assert-Rejected { Initialize-NipatRuntimeTarget $resume $asset '' '' } 'reject different product before initializing owner'
    $registrations[$resume.Distro].product = 'nipat-runtime-v1'
    $registrations[$resume.Distro].owner = 'wrong-owner'
    Assert-Rejected { Initialize-NipatRuntimeTarget $resume $asset '' '' } 'owned marker cannot be replaced on retry'

    $occupiedHash = '1' * 64
    $occupied = Get-NipatRuntimeTarget $wsl $occupiedHash @($registrations.Keys)
    [IO.Directory]::CreateDirectory($occupied.Directory) | Out-Null
    [IO.File]::WriteAllText((Join-Path $occupied.Directory 'keep.txt'), 'preserve')
    Assert-Rejected { Initialize-NipatRuntimeTarget $occupied $asset '' '' } 'unregistered nonempty directory is never overwritten'
    Assert-Test ([IO.File]::ReadAllText((Join-Path $occupied.Directory 'keep.txt')) -ceq 'preserve') 'existing directory content preserved'

    $project = Join-Path $temporary 'app'
    $backendPath = Join-Path $project '.runtime/backend.json'
    $statePath = Join-Path $project '.runtime/installer/state.json'
    $runtimeImagePath = Join-Path $project '.runtime/runtime-image.txt'
    $data = Join-Path $temporary 'custom-data'
    $runs = Join-Path $temporary 'custom-runs'
    [IO.Directory]::CreateDirectory($data) | Out-Null
    [IO.Directory]::CreateDirectory($runs) | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'input.txt'), 'input sentinel')
    [IO.File]::WriteAllText((Join-Path $runs 'result.txt'), 'result sentinel')
    $previous = [pscustomobject]@{ schema_version = 1; backend = 'wsl'; wsl_distro = 'NIPAT-Runtime'; runtime_image = ('sha256:' + ('2' * 64)); data_dir = $data; runs_dir = $runs }
    Write-NipatJsonAtomic $backendPath $previous
    [IO.File]::WriteAllText($runtimeImagePath, $previous.runtime_image)
    Write-NipatJsonAtomic $statePath ([ordered]@{ schema_version = 1; phase = 'ready'; source_commit = ('3' * 40) })
    $manifest = [pscustomobject]@{ source_commit = ('4' * 40); assets = [pscustomobject]@{ rootfs = [pscustomobject]@{ sha256 = $hash } } }
    $snapshotPath = Save-NipatRecoverySnapshot $project $manifest
    $snapshotBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($snapshotPath))
    $snapshot = Get-Content -LiteralPath $snapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $savedBackend = $snapshot.previous_files.PSObject.Properties['.runtime/backend.json'].Value
    Assert-Test ($savedBackend.content_base64 -ceq [Convert]::ToBase64String([IO.File]::ReadAllBytes($backendPath))) 'snapshot preserves previous backend bytes'
    $state = [ordered]@{ schema_version = 1; phase = 'verifying_installation'; updated_utc = ''; wsl_distro = $target.Distro; rootfs_sha256 = $hash }
    Write-NipatJsonAtomic $statePath $state
    Save-NipatRecoverySnapshot $project $manifest | Out-Null
    Assert-Test ([Convert]::ToBase64String([IO.File]::ReadAllBytes($snapshotPath)) -ceq $snapshotBytes) 'retry never overwrites first recovery evidence'
    $roots = Get-NipatPreviousDataRoots $project (Join-Path $temporary 'default')
    Assert-Test ($roots.data_dir -ceq $data -and $roots.runs_dir -ceq $runs) 'custom data and result roots survive update'
    $configuration = [ordered]@{ schema_version = 1; backend = 'wsl'; wsl_distro = $target.Distro; rootfs_sha256 = $hash; runtime_image = ('sha256:' + ('5' * 64)); data_dir = $roots.data_dir; runs_dir = $roots.runs_dir }
    $backendBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($backendPath))
    $runtimeImageBefore = [IO.File]::ReadAllText($runtimeImagePath)
    $envBefore = [Environment]::GetEnvironmentVariable('NIPAT_WSL_DISTRO', 'Process')
    $observedCandidate = @{}
    Assert-Rejected {
        Complete-NipatRuntimeActivation $project $statePath $state $configuration {
            $observedCandidate.distro = $env:NIPAT_WSL_DISTRO
            $observedCandidate.image = $env:NIPAT_RUNTIME_IMAGE
            $observedCandidate.backend = [Convert]::ToBase64String([IO.File]::ReadAllBytes($backendPath))
            throw 'Simulated self-test failure.'
        }
    } 'failed self-test prevents activation'
    Assert-Test ($observedCandidate.distro -ceq $target.Distro -and $observedCandidate.image -ceq $configuration.runtime_image) 'validation uses candidate distro and image'
    Assert-Test ($observedCandidate.backend -ceq $backendBefore) 'previous selection remains published during validation'
    Assert-Test ([Convert]::ToBase64String([IO.File]::ReadAllBytes($backendPath)) -ceq $backendBefore) 'failed validation preserves previous backend'
    Assert-Test ([IO.File]::ReadAllText($runtimeImagePath) -ceq $runtimeImageBefore) 'failed validation preserves previous runtime image file'
    $savedState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($savedState.phase -cne 'ready') 'failed validation never publishes ready state'
    Assert-Test ([Environment]::GetEnvironmentVariable('NIPAT_WSL_DISTRO', 'Process') -ceq $envBefore) 'candidate environment restored after failure'
    # Inject only the persistence boundary; activation and verification use production helpers.
    $originalJsonWriter = (Get-Command Write-NipatJsonAtomic).ScriptBlock
    $failedWritePath = $backendPath
    function Write-NipatJsonAtomic([string] $Path, $Value) {
        if ([IO.Path]::GetFullPath($Path) -ceq [IO.Path]::GetFullPath($script:failedWritePath)) {
            throw 'Simulated persistence failure.'
        }
        & $script:originalJsonWriter $Path $Value
    }
    try {
        Assert-Rejected { Complete-NipatRuntimeActivation $project $statePath $state $configuration {} } 'failed backend publication rejects activation'
        Assert-Test ([Convert]::ToBase64String([IO.File]::ReadAllBytes($backendPath)) -ceq $backendBefore -and
            [IO.File]::ReadAllText($runtimeImagePath) -ceq $runtimeImageBefore) 'failed backend write preserves old selection files'
        $savedState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Test ($savedState.phase -cne 'ready') 'failed backend write cannot publish ready'
        $failedWritePath = $statePath
        Assert-Rejected { Complete-NipatRuntimeActivation $project $statePath $state $configuration {} } 'failed ready publication rejects activation'
        $savedState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pendingBackend = Get-Content -LiteralPath $backendPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Test ($savedState.phase -cne 'ready' -and $pendingBackend.wsl_distro -ceq $target.Distro) 'interrupted activation leaves app blocked despite prepared selection'
        $retryRoots = Get-NipatPreviousDataRoots $project (Join-Path $temporary 'default')
        Assert-Test ($retryRoots.data_dir -ceq $data -and $retryRoots.runs_dir -ceq $runs) 'retry after interrupted publication preserves custom roots'
    } finally {
        Set-Item -Path Function:Write-NipatJsonAtomic -Value $originalJsonWriter
    }
    $state = $savedState
    Complete-NipatRuntimeActivation $project $statePath $state $configuration {
        Assert-Test ($env:NIPAT_DATA_DIR -ceq $data -and $env:NIPAT_RUNS_DIR -ceq $runs) 'candidate checks use preserved data roots'
        $notReady = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Test ($notReady.phase -cne 'ready') 'ready marker remains unset until checks finish'
    }
    $selected = Get-Content -LiteralPath $backendPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ready = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($selected.wsl_distro -ceq $target.Distro -and $ready.phase -ceq 'ready') 'successful retry selects candidate and publishes ready state'
    Assert-Test ($selected.rootfs_sha256 -ceq $hash -and $ready.rootfs_sha256 -ceq $hash) 'selected rootfs is bound in state and configuration'
    Assert-Test ([Environment]::GetEnvironmentVariable('NIPAT_WSL_DISTRO', 'Process') -ceq $envBefore) 'candidate environment restored after successful activation'
    Assert-Test ([IO.File]::ReadAllText((Join-Path $data 'input.txt')) -ceq 'input sentinel' -and [IO.File]::ReadAllText((Join-Path $runs 'result.txt')) -ceq 'result sentinel') 'data and existing results remain unchanged'
    $selected.data_dir = 'relative-data'
    Write-NipatJsonAtomic $backendPath $selected
    Assert-Rejected { Get-NipatPreviousDataRoots $project $temporary } 'invalid previous data root is rejected rather than reset'
    Assert-Test (@($calls | Where-Object { $_[0] -in @('--unregister', '--terminate', '--shutdown') }).Count -eq 0) 'migration never deletes or stops another runtime'
    Write-Host "PASS: $checks migration assertions."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
