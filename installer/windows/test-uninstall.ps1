# Exercise real removal planning and file operations in temporary directories.
# Only layout discovery and the Windows registry/WSL boundary are simulated.
. (Join-Path $PSScriptRoot 'uninstall-runtime.ps1') -LibraryOnly
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-removal-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$oldLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $temporary 'LocalAppData'
$assertions = 0
$script:TestLayouts = @()
$script:TestRegistrations = @()
$script:TestOwners = @{}
$script:RemovalCalls = @()
$script:FailedDistro = ''
$script:KeepRegistration = $false

function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:assertions += 1
}

function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}

function Get-NipatKnownInstallLayouts([string] $Project) { return $script:TestLayouts }
function Get-NipatRemovalRegistrations { return $script:TestRegistrations }
function Assert-NipatDistroLocation([string] $Distro, [string] $ExpectedDirectory) {
    $matches = @($script:TestRegistrations | Where-Object { $_.DistributionName -ceq $Distro })
    if ($matches.Count -ne 1 -or $matches[0].Version -ne 2 -or
        (Get-NipatRemovalRegistrationPath $matches[0].BasePath) -ine (Get-NipatRemovalPath $ExpectedDirectory)) {
        throw 'Test registry does not match the requested distribution.'
    }
}
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    if ($Arguments.Count -eq 2 -and $Arguments[0] -ceq '--unregister') {
        $distro = $Arguments[1]
        $script:RemovalCalls += $distro
        if ($distro -ceq $script:FailedDistro) { throw 'Simulated WSL unregister failure.' }
        if (-not $script:KeepRegistration) {
            $script:TestRegistrations = @($script:TestRegistrations | Where-Object { $_.DistributionName -cne $distro })
        }
        return [pscustomobject]@{ ExitCode = 0; Text = ''; ErrorText = '' }
    }
    if ($Arguments.Count -eq 7 -and ($Arguments[0..4] -join '|') -cmatch '^--distribution\|NIPAT-Desktop-[a-f0-9-]+\|--user\|root\|--exec$' -and
        $Arguments[5] -ceq '/usr/bin/cat') {
        $distro = $Arguments[1]
        if (-not $script:TestOwners.ContainsKey($distro)) { throw 'Unexpected access to an unowned distribution.' }
        if ($Arguments[6] -ceq '/etc/nipat-runtime-id') {
            return [pscustomobject]@{ ExitCode = 0; Text = 'nipat-runtime-v1'; ErrorText = '' }
        }
        if ($Arguments[6] -ceq '/var/lib/nipat/owner-id') {
            return [pscustomobject]@{ ExitCode = 0; Text = $script:TestOwners[$distro]; ErrorText = '' }
        }
    }
    throw ('Unexpected WSL command: ' + ($Arguments -join ' '))
}

function New-RemovalFixture([string] $Name, [string] $HashCharacter = 'a', [switch] $LocationBound) {
    $root = Join-Path $temporary $Name
    $layout = [pscustomobject]@{
        schema_version = 1; installation_channel = 'desktop'
        app_dir = (Join-Path $root 'app'); runtime_dir = (Join-Path $root 'wsl')
        cache_dir = (Join-Path $root 'cache'); data_dir = (Join-Path $root 'data')
        runs_dir = (Join-Path $root 'results')
    }
    foreach ($name in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        [IO.Directory]::CreateDirectory($layout.$name) | Out-Null
    }
    foreach ($role in @('runtime', 'cache')) {
        $directory = if ($role -ceq 'runtime') { $layout.runtime_dir } else { $layout.cache_dir }
        [IO.File]::WriteAllText((Join-Path $directory '.nipat-storage.ini'),
            "[NIPAT]`nschema_version=1`ninstallation_channel=desktop`nrole=$role`n", [Text.Encoding]::ASCII)
    }
    $hash = $HashCharacter * 64
    $distro = if ($LocationBound) { Get-NipatRuntimeDistroName $hash $layout.runtime_dir }
        else { (Get-NipatInstallationProfile).distro_prefix + $hash.Substring(0, 40) }
    $owner = [Guid]::NewGuid().ToString('N')
    $directory = Join-Path $layout.runtime_dir $distro
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $receipt = Join-Path (Join-Path $layout.runtime_dir 'registrations') ($distro + '.json')
    Write-NipatJsonAtomic $receipt ([ordered]@{
        schema_version = 1; installation_channel = 'desktop'; distro = $distro
        owner_id = $owner; rootfs_sha256 = $hash; status = 'owned'
    })
    $payload = [byte[]]@(1, 2, 3, 4, 5)
    $temporaryAsset = Join-Path $layout.cache_dir 'asset.tmp'
    [IO.File]::WriteAllBytes($temporaryAsset, $payload)
    $digest = (Get-FileHash -LiteralPath $temporaryAsset -Algorithm SHA256).Hash.ToLowerInvariant()
    $cacheFile = Join-Path $layout.cache_dir ($digest + '-nipat-scientific-runtime-0.6.0-amd64.tar.gz')
    [IO.File]::Move($temporaryAsset, $cacheFile)
    $unknownFile = Join-Path $layout.cache_dir 'research-notes.txt'
    [IO.File]::WriteAllText($unknownFile, 'Keep this file.')
    [IO.File]::WriteAllText((Join-Path $layout.data_dir 'input.txt'), 'Original data.')
    [IO.File]::WriteAllText((Join-Path $layout.runs_dir 'result.txt'), 'Original result.')
    $registration = [pscustomobject]@{ DistributionName = $distro; BasePath = $directory; Version = 2 }
    $script:TestLayouts += $layout
    $script:TestRegistrations += $registration
    $script:TestOwners[$distro] = $owner
    return [pscustomobject]@{
        Layout = $layout; Distro = $distro; Directory = $directory; Receipt = $receipt
        CacheFile = $cacheFile; UnknownFile = $unknownFile; Registration = $registration
    }
}

function Reset-RemovalFixture {
    $script:TestLayouts = @()
    $script:TestRegistrations = @(
        [pscustomobject]@{ DistributionName = 'docker-desktop'; BasePath = (Join-Path $temporary 'unrelated-docker'); Version = 2 },
        [pscustomobject]@{ DistributionName = 'NIPAT-Runtime'; BasePath = (Join-Path $temporary 'stable-runtime'); Version = 2 },
        [pscustomobject]@{ DistributionName = ('NIPAT-05-Preview-' + ('a' * 40)); BasePath = (Join-Path $temporary 'preview-runtime'); Version = 2 }
    )
    $script:TestOwners = @{}
    $script:RemovalCalls = @()
    $script:FailedDistro = ''
    $script:KeepRegistration = $false
}

try {
    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'success with spaces' -LocationBound
    $plan = Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir
    Assert-Test ($plan.Targets.Count -eq 1 -and $plan.CacheFiles.Count -eq 1) 'plan selects the owned runtime and verified archive only'
    Assert-Test ($script:RemovalCalls.Count -eq 0 -and (Test-Path -LiteralPath $fixture.CacheFile)) 'planning has no destructive operations'
    Invoke-NipatRuntimeRemoval $plan
    Assert-Test ($script:RemovalCalls.Count -eq 1 -and $script:RemovalCalls[0] -ceq $fixture.Distro) 'only the selected Desktop is unregistered'
    Assert-Test (-not (Test-Path -LiteralPath $fixture.Receipt) -and -not (Test-Path -LiteralPath $fixture.CacheFile)) 'successful cleanup removes receipt and verified archive'
    Assert-Test ((Test-Path -LiteralPath $fixture.UnknownFile) -and
        (Test-Path -LiteralPath (Join-Path $fixture.Layout.data_dir 'input.txt')) -and
        (Test-Path -LiteralPath (Join-Path $fixture.Layout.runs_dir 'result.txt'))) 'unknown files, inputs and results survive cleanup'
    Assert-Test (@($script:TestRegistrations | Where-Object { $_.DistributionName -in @('docker-desktop', 'NIPAT-Runtime') }).Count -eq 2) 'Docker Desktop and stable WSL registrations survive'
    Assert-Test (@($script:TestRegistrations | Where-Object { $_.DistributionName -ceq ('NIPAT-05-Preview-' + ('a' * 40)) }).Count -eq 1) 'the 0.5 Preview registration survives even when its rootfs hash matches'
    $retry = Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir
    Invoke-NipatRuntimeRemoval $retry
    Assert-Test ($retry.Targets.Count -eq 0 -and $retry.CacheFiles.Count -eq 0 -and $script:RemovalCalls.Count -eq 1) 'completed cleanup is idempotent'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'missing receipt'
    [IO.File]::Delete($fixture.Receipt)
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'registered runtime without ownership receipt blocks cleanup'
    Assert-Test ($script:RemovalCalls.Count -eq 0 -and (Test-Path -LiteralPath $fixture.CacheFile)) 'unowned runtime blocks all deletion, including cache'

    foreach ($foreignChannel in @('stable', 'preview-0.5')) {
        Reset-RemovalFixture
        $fixture = New-RemovalFixture ('foreign channel ' + $foreignChannel)
        $record = Get-Content -LiteralPath $fixture.Receipt -Raw | ConvertFrom-Json
        $record.installation_channel = $foreignChannel
        Write-NipatJsonAtomic $fixture.Receipt $record
        Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'foreign receipt channel is rejected'
        Assert-Test ($script:RemovalCalls.Count -eq 0 -and (Test-Path -LiteralPath $fixture.CacheFile)) 'foreign ownership prevents unregister and cache removal'
    }

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'different registered location'
    $fixture.Registration.BasePath = Join-Path $temporary 'not-this-runtime'
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'registry BasePath mismatch is rejected before unregister'
    Assert-Test ($script:RemovalCalls.Count -eq 0) 'location mismatch cannot invoke unregister'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'owner mismatch'
    $script:TestOwners[$fixture.Distro] = '0' * 32
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'internal random owner marker must match receipt'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'orphan files'
    $script:TestRegistrations = @($script:TestRegistrations | Where-Object { $_.DistributionName -cne $fixture.Distro })
    [IO.File]::WriteAllText((Join-Path $fixture.Directory 'ext4.vhdx'), 'Unregistered disk that needs manual review.')
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'unregistered directory containing files is preserved'
    Assert-Test (Test-Path -LiteralPath (Join-Path $fixture.Directory 'ext4.vhdx')) 'orphan disk is never recursively deleted'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'empty orphan'
    $script:TestRegistrations = @($script:TestRegistrations | Where-Object { $_.DistributionName -cne $fixture.Distro })
    Invoke-NipatRuntimeRemoval (Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir)
    Assert-Test ($script:RemovalCalls.Count -eq 0 -and -not (Test-Path -LiteralPath $fixture.Receipt)) 'empty unregistered runtime is cleaned without calling WSL'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'overlap with analysis'
    $fixture.Layout.data_dir = $fixture.Layout.runtime_dir
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'runtime overlapping a data root is rejected'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'cache marker missing'
    [IO.File]::Delete((Join-Path $fixture.Layout.cache_dir '.nipat-storage.ini'))
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'custom cache without storage marker is rejected'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'default cache ownership'
    $legacyCache = Join-Path (Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop') 'cache'
    [IO.Directory]::CreateDirectory((Split-Path -Parent $legacyCache)) | Out-Null
    Move-Item -LiteralPath $fixture.Layout.cache_dir -Destination $legacyCache
    $fixture.Layout.cache_dir = $legacyCache
    $fixture.CacheFile = Join-Path $legacyCache ([IO.Path]::GetFileName($fixture.CacheFile))
    [IO.File]::Delete((Join-Path $legacyCache '.nipat-storage.ini'))
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'the default cache also requires an ownership marker'
    Assert-Test ($script:RemovalCalls.Count -eq 0 -and (Test-Path -LiteralPath $fixture.CacheFile) -and
        (Test-Path -LiteralPath (Join-Path $legacyCache 'research-notes.txt'))) 'unmarked default cache stops removal before changing files or WSL'
    [IO.File]::WriteAllText((Join-Path $legacyCache '.nipat-storage.ini'),
        "[NIPAT]`nschema_version=1`ninstallation_channel=desktop`nrole=cache`n", [Text.Encoding]::ASCII)
    Invoke-NipatRuntimeRemoval (Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir)
    Assert-Test (-not (Test-Path -LiteralPath $fixture.CacheFile) -and
        (Test-Path -LiteralPath (Join-Path $legacyCache 'research-notes.txt'))) 'marked default cache removes verified archives and preserves research notes'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'foreign cache marker'
    [IO.File]::WriteAllText((Join-Path $fixture.Layout.cache_dir '.nipat-storage.ini'),
        "[NIPAT]`nschema_version=1`ninstallation_channel=stable`nrole=cache`n", [Text.Encoding]::ASCII)
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'a foreign cache marker is never adopted'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'foreign runtime marker'
    [IO.File]::WriteAllText((Join-Path $fixture.Layout.runtime_dir '.nipat-storage.ini'),
        "[NIPAT]`nschema_version=1`ninstallation_channel=stable`nrole=runtime`n", [Text.Encoding]::ASCII)
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'a foreign runtime storage marker is never adopted'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'changed cache'
    [IO.File]::WriteAllText($fixture.CacheFile, 'Modified bytes.')
    Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'hash-addressed archive must match its advertised digest'
    Assert-Test ($script:RemovalCalls.Count -eq 0) 'invalid cache blocks runtime removal too'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'plan changed'
    $plan = Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir
    [IO.File]::WriteAllText($fixture.CacheFile, 'Changed after validation.')
    Assert-Rejected { Invoke-NipatRuntimeRemoval $plan } 'entire plan is revalidated before the first destructive operation'
    Assert-Test ($script:RemovalCalls.Count -eq 0 -and (Test-Path -LiteralPath $fixture.Receipt)) 'changed cache leaves runtime and receipt untouched'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'unregister ineffective'
    $script:KeepRegistration = $true
    Assert-Rejected { Invoke-NipatRuntimeRemoval (Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir) } 'successful process exit is insufficient if the WSL registration remains'
    Assert-Test ((Test-Path -LiteralPath $fixture.Receipt) -and (Test-Path -LiteralPath $fixture.CacheFile)) 'remaining registration retains its receipt and cache'

    Reset-RemovalFixture
    $first = New-RemovalFixture 'partial removal first' 'a'
    $second = New-RemovalFixture 'partial removal second' 'b'
    $plan = Get-NipatRuntimeRemovalPlan $first.Layout.app_dir
    $plan.Targets = @($plan.Targets | Sort-Object Distro)
    $script:FailedDistro = $second.Distro
    Assert-Rejected { Invoke-NipatRuntimeRemoval $plan } 'failure during removal stops subsequent destructive actions'
    Assert-Test (-not (Test-Path -LiteralPath $first.Receipt) -and
        (Test-Path -LiteralPath $second.Receipt) -and (Test-Path -LiteralPath $first.CacheFile) -and
        (Test-Path -LiteralPath $second.CacheFile)) 'partial failure records completed work and preserves unprocessed archives'
    $script:FailedDistro = ''
    Invoke-NipatRuntimeRemoval (Get-NipatRuntimeRemovalPlan $first.Layout.app_dir)
    Assert-Test (-not (Test-Path -LiteralPath $second.Receipt) -and -not (Test-Path -LiteralPath $second.CacheFile)) 'retry after a partial failure completes remaining cleanup'

    Reset-RemovalFixture
    $fixture = New-RemovalFixture 'junction rejection'
    $outside = Join-Path $temporary 'outside research folder'
    [IO.Directory]::CreateDirectory($outside) | Out-Null
    $sentinel = Join-Path $outside 'keep.txt'
    [IO.File]::WriteAllText($sentinel, 'Never remove this file.')
    $junction = Join-Path $fixture.Layout.runtime_dir 'redirect'
    New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
    try {
        Assert-Rejected { Get-NipatRuntimeRemovalPlan $fixture.Layout.app_dir } 'junction inside managed runtime is rejected'
        Assert-Test ((Test-Path -LiteralPath $sentinel) -and $script:RemovalCalls.Count -eq 0) 'junction target remains untouched'
    } finally {
        [IO.Directory]::Delete($junction, $false)
    }

    Write-Host "PASS: $assertions optional uninstall assertions."
} finally {
    $env:LOCALAPPDATA = $oldLocalAppData
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
