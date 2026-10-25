# Real Windows handles and child processes; no WSL, Docker, installation or network activity.
. (Join-Path $PSScriptRoot 'activity-lock.ps1')
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-activity-test-' + [Guid]::NewGuid().ToString('N'))
$originalLocalAppData = $env:LOCALAPPDATA
$originalToken = [Environment]::GetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', 'Process')
$lease = $null
$shared = $null
$assertions = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:assertions += 1
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    $env:LOCALAPPDATA = Join-Path $temporary 'local data with spaces'
    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $null, 'Process')
    Initialize-NipatActivityNative
    $path = Get-NipatActivityLockPath
    Assert-Test (-not (Test-Path -LiteralPath $path)) 'path discovery does not create the lock file'
    $shared = [NipatActivityNative]::CreateFileW($path, 2147483648, 3,
        [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
    Assert-Test (-not $shared.IsInvalid) 'a running client acquires a shared handle'
    Assert-Rejected { Enter-NipatInstallationActivity } 'standalone setup and removal refuse a running session'
    Assert-Test ([string]::IsNullOrEmpty($env:NIPAT_SETUP_ACTIVITY_TOKEN)) 'failed acquisition leaves no setup token'
    $shared.Dispose(); $shared = $null

    $lease = Enter-NipatInstallationActivity
    Assert-Test (-not $lease.Borrowed) 'standalone setup owns its exclusive lease'
    Assert-Test ($lease.Token -cmatch ("^$PID`:[a-f0-9]{32}$")) 'standalone token identifies its live PowerShell process'
    Assert-Test (-not [NipatActivityNative]::IsAuthorizedSetupChild($lease.Token)) 'a token does not exempt its owner as its own ancestor'
    $blocked = [NipatActivityNative]::CreateFileW($path, 2147483648, 3,
        [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
    try { Assert-Test $blocked.IsInvalid 'a standalone preparation blocks new client sessions' }
    finally { $blocked.Dispose() }

    $child = Join-Path $temporary 'child-activity.ps1'
    [IO.File]::WriteAllText($child, @'
param([string] $Helper, [string] $ResultFile)
. $Helper
$childLease = $null
try {
    $childLease = Enter-NipatInstallationActivity
    $result = @{ borrowed = $childLease.Borrowed; token = $env:NIPAT_SETUP_ACTIVITY_TOKEN }
    [IO.File]::WriteAllText($ResultFile, ($result | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
} catch {
    [IO.File]::WriteAllText($ResultFile, $_.Exception.Message, (New-Object Text.UTF8Encoding($false)))
    exit 1
} finally { Exit-NipatInstallationActivity $childLease }
'@, (New-Object Text.UTF8Encoding($false)))
    $childResult = Join-Path $temporary 'child-result.json'
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $child `
        -Helper (Join-Path $PSScriptRoot 'activity-lock.ps1') -ResultFile $childResult
    Assert-Test ($LASTEXITCODE -eq 0) 'a real descendant can enter while its ancestor holds the exclusive lease'
    $result = Get-Content -LiteralPath $childResult -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($result.borrowed -and $result.token -ceq $lease.Token) 'bootstrap child borrows the existing lease without replacing its token'
    Assert-Test (-not $lease.Handle.IsClosed) 'child completion does not dispose the owner file handle'

    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', ("$PID`:" + ('0' * 32)), 'Process')
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $child `
        -Helper (Join-Path $PSScriptRoot 'activity-lock.ps1') -ResultFile $childResult
    Assert-Test ($LASTEXITCODE -ne 0) 'an ancestor PID with no matching live event cannot bypass the lease'
    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', ('4294967295:' + $lease.Token.Split(':')[1]), 'Process')
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $child `
        -Helper (Join-Path $PSScriptRoot 'activity-lock.ps1') -ResultFile $childResult
    Assert-Test ($LASTEXITCODE -ne 0) 'an event without a real ancestor cannot bypass the lease'
    $oldToken = $lease.Token
    Exit-NipatInstallationActivity $lease; $lease = $null
    Assert-Test ([string]::IsNullOrEmpty($env:NIPAT_SETUP_ACTIVITY_TOKEN)) 'owner cleanup removes the token'

    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $oldToken, 'Process')
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $child `
        -Helper (Join-Path $PSScriptRoot 'activity-lock.ps1') -ResultFile $childResult
    Assert-Test ($LASTEXITCODE -eq 0) 'a subsequent independent preparation can acquire the released file'
    $result = Get-Content -LiteralPath $childResult -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test (-not $result.borrowed -and $result.token -cne $oldToken) 'a stale event token does not authorize borrowing'
    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $null, 'Process')

    try {
        $lease = Enter-NipatInstallationActivity
        throw 'simulated setup failure'
    } catch {
        Assert-Test ($_.Exception.Message -ceq 'simulated setup failure') 'exercise caller failure after acquisition'
    } finally {
        Exit-NipatInstallationActivity $lease; $lease = $null
    }
    $lease = Enter-NipatInstallationActivity
    Assert-Test (-not $lease.Borrowed) 'a failed preparation releases the lease for retry'
    Write-Host "PASS: $assertions activity lease checks; shared clients, standalone setup/removal, child authorization and failure recovery."
} finally {
    Exit-NipatInstallationActivity $lease
    if ($null -ne $shared) { $shared.Dispose() }
    $env:LOCALAPPDATA = $originalLocalAppData
    [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $originalToken, 'Process')
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
