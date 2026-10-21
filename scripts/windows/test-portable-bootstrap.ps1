# Exercise production preparation decisions with offline Docker/process boundaries.
# Windows CI runs this with Windows PowerShell 5.1 before building release assets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
. (Join-Path $PSScriptRoot 'portable-bootstrap.ps1')

$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Portable bootstrap check failed: $Message" }
    $script:checks++
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
function Write-Json([string] $Path, $Value) {
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-bootstrap-test-' + [Guid]::NewGuid().ToString('N'))
$script:SetupCalls = 0
$script:DockerCalls = 0
$script:SetupExitCode = 0
$script:WriteReady = $true
$script:ImageAvailable = $true
$script:DockerAvailable = $true
$script:LocalImageId = 'sha256:' + ('b' * 64)
function Assert-NipatDocker {
    $script:DockerCalls++
    if (-not $script:DockerAvailable) { throw 'Docker Desktop must be started.' }
}
function Get-NipatImage([string] $Image) {
    if ($script:ImageAvailable -and $Image -ceq $script:LocalImageId) {
        return [pscustomobject]@{ Id = $Image; Os = 'linux'; Architecture = 'amd64' }
    }
    return $null
}
function Invoke-NipatPortableSetupProcess([string] $Project) {
    $script:SetupCalls++
    if ($script:SetupExitCode -eq 0 -and $script:WriteReady) {
        $script:ImageAvailable = $true
        Complete-NipatPortableSetup $Project (Get-NipatPortablePackage $Project)
    }
    return $script:SetupExitCode
}

try {
    $project = Join-Path $temporary 'NIPAT project with spaces'
    $distribution = Join-Path $project '.distribution'
    $pythonDirectory = Join-Path $project '.runtime\python'
    [IO.Directory]::CreateDirectory($distribution) | Out-Null
    [IO.Directory]::CreateDirectory($pythonDirectory) | Out-Null
    $statePath = Join-Path $project '.runtime\portable-setup.json'
    $releasePath = Join-Path $project 'release.json'
    $runtimePath = Join-Path $distribution 'runtime.json'
    $archivePath = Join-Path $distribution 'runtime.tar'
    'version = "0.4.1"' | Set-Content -LiteralPath (Join-Path $project 'pyproject.toml') -Encoding ASCII
    [IO.File]::WriteAllBytes($archivePath, [byte[]]@(1, 2, 3, 4))
    [IO.File]::WriteAllBytes((Join-Path $distribution 'python-3.12.10-embed-amd64.zip'), [byte[]]@(1))
    $runtime = [ordered]@{
        schema_version = 1; os = 'linux'; architecture = 'amd64'
        image_id = 'sha256:' + ('a' * 64)
        archive_sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        archive_bytes = 4; source_commit = 'c' * 40
    }
    $release = [ordered]@{
        schema_version = 1; package_version = '0.4.1'
        source_git = @{ available = $true; dirty = $false; commit = $runtime.source_commit }
        python = @{ version = '3.12.10'; architecture = 'amd64'; archive_sha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3' }
        runtime = $runtime
    }
    Write-Json $runtimePath $runtime
    [IO.File]::WriteAllBytes((Get-NipatPython $project), [byte[]]@(10, 11, 12))
    '3.12.10' | Set-Content -LiteralPath (Join-Path $pythonDirectory 'nipat-python.ready') -Encoding ASCII
    '.' | Set-Content -LiteralPath (Join-Path $pythonDirectory 'python312._pth') -Encoding ASCII
    $script:LocalImageId | Set-Content -LiteralPath (Join-Path $project '.runtime\runtime-image.txt') -Encoding ASCII

    $sourceProject = Join-Path $temporary 'source checkout'
    [IO.Directory]::CreateDirectory($sourceProject) | Out-Null
    Assert-Test ($null -eq (Get-NipatPortablePackage $sourceProject)) 'a source checkout does not become a packaged installation'
    Assert-Test ((Initialize-NipatPortableLaunch $sourceProject @('wizard')) -eq 0 -and $script:SetupCalls -eq 0) 'source wizard keeps its explicit setup path'
    Assert-Rejected { Get-NipatPortablePackage $project } 'bundled runtime without release provenance cannot fall back to source mode'
    @{ schema_version = 1; distribution = 'docker-desktop-installer' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $distribution 'docker-desktop.json') -Encoding UTF8
    Assert-Rejected { Get-NipatPortablePackage $project } 'installed application without release metadata cannot skip preparation'
    'truncated' | Set-Content -LiteralPath $releasePath -Encoding ASCII
    Assert-Rejected { Get-NipatPortablePackage $project } 'installed application with corrupt release metadata is rejected'
    $release.runtime = $null
    Write-Json $releasePath $release
    Assert-Rejected { Get-NipatPortablePackage $project } 'installed application with no release runtime cannot fall back to source mode'
    $release.runtime = $runtime
    Write-Json $releasePath $release
    $package = Get-NipatPortablePackage $project
    Assert-Test ($package.source_image_id -cne $script:LocalImageId) 'fixture exercises distinct exported and locally loaded image IDs'
    Assert-Test (-not (Test-NipatPortableSetupReady $project $package) -and $script:DockerCalls -eq 0) 'Python and an imported image alone are not a verified installation'
    foreach ($arguments in @(@('--dry-run', 'wizard'), @('--help'), @('-h'), @('--version'))) {
        Assert-Test ((Initialize-NipatPortableLaunch $project $arguments) -eq 0) ('preview/information avoids setup: ' + ($arguments -join ' '))
    }
    Assert-Test ($script:SetupCalls -eq 0) 'preview and information commands start no preparation process'
    Assert-Rejected { Initialize-NipatPortableLaunch $project @('dnp-call') } 'unprepared direct analyses do not trigger an implicit installation'
    Assert-Test ($script:SetupCalls -eq 0) 'unprepared direct analysis never starts setup'

    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0) 'first wizard launch prepares successfully'
    Assert-Test ($script:SetupCalls -eq 1 -and (Test-Path -LiteralPath $statePath)) 'first preparation commits verified readiness'
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Assert-Test ($state.local_image_id -ceq $script:LocalImageId -and $state.source_image_id -ceq $runtime.image_id) 'ready state preserves both local and source identity'
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0 -and $script:SetupCalls -eq 1) 'second launch reuses the verified setup'

    $script:DockerAvailable = $false
    Assert-Rejected { Initialize-NipatPortableLaunch $project @('wizard') } 'stopped Docker gives an actionable failure'
    Assert-Test ($script:SetupCalls -eq 1 -and (Test-Path -LiteralPath $statePath)) 'stopped Docker neither reinstalls nor loses readiness'
    $script:DockerAvailable = $true
    $script:ImageAvailable = $false
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0 -and $script:SetupCalls -eq 2) 'a removed local image is prepared again'

    'modified Python configuration' | Set-Content -LiteralPath (Join-Path $pythonDirectory 'python312._pth') -Encoding ASCII
    Assert-Test (-not (Test-NipatPortableSetupReady $project $package)) 'changed Python import configuration invalidates readiness'
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0 -and $script:SetupCalls -eq 3) 'invalid local configuration reruns the preparation boundary'
    [IO.File]::WriteAllBytes((Get-NipatPython $project), [byte[]]@(20, 21, 22))
    Assert-Test (-not (Test-NipatPortableSetupReady $project $package)) 'replaced Python executable invalidates readiness'
    Complete-NipatPortableSetup $project $package
    'invalid' | Set-Content -LiteralPath $statePath -Encoding ASCII
    Assert-Test (-not (Test-NipatPortableSetupReady $project $package)) 'truncated preparation state is never accepted'
    Remove-Item -LiteralPath $statePath
    $script:SetupExitCode = 17
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 17) 'failed preparation propagates its exit code'
    Assert-Test (-not (Test-Path -LiteralPath $statePath)) 'failed preparation leaves no false ready marker'
    $script:SetupExitCode = 0
    $script:WriteReady = $false
    Assert-Rejected { Initialize-NipatPortableLaunch $project @('wizard') } 'a successful child exit without verified state cannot launch the menu'
    Assert-Test (-not (Test-Path -LiteralPath $statePath)) 'an incomplete child remains retryable'
    $script:WriteReady = $true
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0 -and (Test-NipatPortableSetupReady $project $package)) 'retry after a failed first setup can complete'
    $release['source_sha256'] = 'd' * 64
    Write-Json $releasePath $release
    Assert-Test (-not (Test-NipatPortableSetupReady $project (Get-NipatPortablePackage $project))) 'a changed release identity requires fresh preparation'
    $release.Remove('source_sha256')
    Write-Json $releasePath $release

    # Installation locking must protect actual concurrent writers, not a stale lock file.
    $lock = Enter-NipatPortableSetupLock $project
    try { Assert-Rejected { $other = Enter-NipatPortableSetupLock $project; $other.Dispose() } 'concurrent preparations cannot acquire the same lock' }
    finally { $lock.Dispose() }
    $lock = Enter-NipatPortableSetupLock $project
    $lock.Dispose()
    Assert-Test $true 'released lock can be acquired on retry'

    $release.package_version = '0.4.2'
    Write-Json $releasePath $release
    Assert-Rejected { Get-NipatPortablePackage $project } 'package version must match the installed source'
    $release.package_version = '0.4.1'
    $release.source_git.dirty = $true
    Write-Json $releasePath $release
    Assert-Rejected { Get-NipatPortablePackage $project } 'dirty source provenance cannot be installed as a release'
    $release.source_git.dirty = $false
    Write-Json $releasePath $release
    $runtime.architecture = 'arm64'
    Write-Json $runtimePath $runtime
    Assert-Rejected { Get-NipatPortablePackage $project } 'runtime manifest architecture is checked before setup'
    $runtime.architecture = 'amd64'
    Write-Json $runtimePath $runtime
    [IO.File]::WriteAllBytes($archivePath, [byte[]]@(1))
    Assert-Rejected { Get-NipatPortablePackage $project } 'truncated runtime archive is rejected before setup'
    [IO.File]::WriteAllBytes($archivePath, [byte[]]@(1, 2, 3, 4))

    # A WSL package uses its existing ownership and migration guards, never Docker auto-setup.
    '{}' | Set-Content -LiteralPath (Join-Path $distribution 'installer-manifest.json') -Encoding ASCII
    $beforeWsl = $script:SetupCalls
    Assert-Test ((Initialize-NipatPortableLaunch $project @('wizard')) -eq 0 -and $script:SetupCalls -eq $beforeWsl) 'WSL installer is excluded from Docker preparation'
    Write-Host "PASS: $checks portable-bootstrap assertions."
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
