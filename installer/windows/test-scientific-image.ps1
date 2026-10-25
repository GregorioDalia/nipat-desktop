# Offline regression tests for verified-archive loading and persisted image identity.
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$assertions = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:assertions++
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-image-' + [Guid]::NewGuid().ToString('N'))
$cache = Join-Path $temporary 'cache'
$offline = Join-Path $temporary 'offline'
[IO.Directory]::CreateDirectory($cache) | Out-Null
[IO.Directory]::CreateDirectory($offline) | Out-Null
$sourceId = 'sha256:' + ('a' * 64)
$localId = 'sha256:' + ('b' * 64)
$calls = New-Object 'Collections.Generic.List[object]'

# Only the WSL boundary is simulated. File hashing/caching, load receipt parsing,
# image selection and release binding use the production functions unchanged.
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    $script:calls.Add($Arguments)
    if (($Arguments[0..4] -join '|') -cne '--distribution|NIPAT-Test|--user|root|--exec') {
        throw 'Unexpected WSL target.'
    }
    if ($Arguments[5] -ceq 'wslpath') {
        return [pscustomobject]@{ ExitCode = 0; Text = '/verified/archive.tar.gz'; ErrorText = '' }
    }
    if (($Arguments[5..13] -join '|') -cne '/usr/bin/env|-i|HOME=/root|LANG=C.UTF-8|PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin|docker|--host|unix:///var/run/docker.sock|image') {
        throw 'Unexpected Docker environment or endpoint.'
    }
    if ($Arguments[14] -ceq 'load') {
        if ($script:failLoad) { throw 'Docker load failed.' }
        return [pscustomobject]@{ ExitCode = 0; Text = $script:loadOutput; ErrorText = '' }
    }
    if ($Arguments[14] -ceq 'inspect') {
        Assert-Test ($Arguments[-1] -ceq $script:receiptId) 'inspect exactly the ID from this load receipt'
        return [pscustomobject]@{ ExitCode = 0; Text = $script:inspectionOutput; ErrorText = '' }
    }
    throw 'Unexpected Docker operation.'
}

try {
    $assetPath = Join-Path $offline 'scientific.tar.gz'
    [IO.File]::WriteAllBytes($assetPath, [byte[]]@(1, 2, 3, 4))
    $asset = [pscustomobject]@{
        file = 'scientific.tar.gz'; size = 4
        sha256 = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest = [pscustomobject]@{
        runtime_image = $sourceId; source_commit = ('c' * 40); release_tag = 'v0.6.0'; installation_profile = (Get-NipatInstallationProfile)
        assets = [pscustomobject]@{ scientific_image = $asset; rootfs = [pscustomobject]@{ sha256 = ('d' * 64) } }
    }
    $failLoad = $false
    foreach ($receiptId in @($sourceId, $localId)) {
        $loadOutput = "Loaded image ID: $receiptId"
        $inspectionOutput = "$receiptId linux amd64"
        $calls.Clear()
        $resolved = Install-NipatScientificImage $manifest $cache $offline 'NIPAT-Test'
        Assert-Test ($resolved -ceq $receiptId) 'classic and containerd IDs are bound to the verified load'
        Assert-Test ($calls.Count -eq 3) 'resolve using path conversion, load and inspect only'
        Assert-Test ($manifest.runtime_image -ceq $sourceId) 'never replace the trusted build identity'
    }

    foreach ($bad in @('', "Loaded image ID: $localId`nLoaded image ID: $sourceId",
        "Loaded image ID: $localId`nLoaded image: other:latest",
        'Loaded image: arbitrary:latest', 'Loaded image ID: sha256:abc',
        "Loaded image ID: $localId`nError unpacking image: fixture error")) {
        Assert-Rejected { Get-NipatLoadedImageId $bad } 'reject absent, ambiguous, tagged, truncated or failed load receipts'
    }
    $receiptId = $localId
    $loadOutput = "Loaded image ID: $receiptId"
    foreach ($inspectionOutput in @("$localId linux arm64", "$localId windows amd64", "$sourceId linux amd64")) {
        Assert-Rejected { Install-NipatScientificImage $manifest $cache $offline 'NIPAT-Test' } 'reject wrong platform or a different inspected ID'
    }
    $failLoad = $true
    $calls.Clear()
    Assert-Rejected { Install-NipatScientificImage $manifest $cache $offline 'NIPAT-Test' } 'stop on nonzero load exit'
    Assert-Test ($calls.Count -eq 2) 'never inspect or choose another image after load failure'
    $failLoad = $false

    $cached = Join-Path $cache ($asset.sha256 + '-' + $asset.file)
    [IO.File]::WriteAllBytes($cached, [byte[]]@(4, 3, 2, 1))
    [IO.File]::WriteAllBytes($assetPath, [byte[]]@(4, 3, 2, 1))
    $calls.Clear()
    Assert-Rejected { Install-NipatScientificImage $manifest $cache $offline 'NIPAT-Test' } 'reject same-size archive corruption even on resume'
    Assert-Test ($calls.Count -eq 0) 'no Docker command for an unverified archive'

    $state = [pscustomobject]@{
        runtime_image = $sourceId; resolved_runtime_image = $localId; runtime_archive_sha256 = $asset.sha256
        installation_channel = (Get-NipatInstallationProfile).channel
        wsl_distro = ((Get-NipatInstallationProfile).distro_prefix + ('d' * 40)); rootfs_sha256 = $manifest.assets.rootfs.sha256
    }
    $configuration = [pscustomobject]@{
        runtime_image = $localId; source_runtime_image = $sourceId; runtime_archive_sha256 = $asset.sha256
        source_commit = $manifest.source_commit; release_tag = $manifest.release_tag
        installation_channel = (Get-NipatInstallationProfile).channel
        wsl_distro = ((Get-NipatInstallationProfile).distro_prefix + ('d' * 40)); rootfs_sha256 = $manifest.assets.rootfs.sha256
    }
    Assert-NipatRuntimeBinding $manifest $state $configuration
    Assert-Test $true 'accept verified mapping between different build and local image IDs'
    foreach ($property in @('runtime_image', 'source_runtime_image', 'runtime_archive_sha256', 'source_commit', 'release_tag', 'wsl_distro', 'rootfs_sha256', 'installation_channel')) {
        $before = $configuration.$property
        $configuration.$property = 'wrong'
        Assert-Rejected { Assert-NipatRuntimeBinding $manifest $state $configuration } "reject changed $property"
        $configuration.$property = $before
    }
    foreach ($property in @('runtime_image', 'resolved_runtime_image', 'runtime_archive_sha256', 'wsl_distro', 'rootfs_sha256', 'installation_channel')) {
        $before = $state.$property
        $state.$property = 'wrong'
        Assert-Rejected { Assert-NipatRuntimeBinding $manifest $state $configuration } "reject inconsistent state $property"
        $state.$property = $before
    }
    foreach ($property in @('wsl_distro', 'rootfs_sha256', 'installation_channel')) {
        $legacyState = $state | ConvertTo-Json | ConvertFrom-Json
        $legacyState.PSObject.Properties.Remove($property)
        Assert-Rejected { Assert-NipatRuntimeBinding $manifest $legacyState $configuration } "require setup for legacy state without $property"
        $legacyConfiguration = $configuration | ConvertTo-Json | ConvertFrom-Json
        $legacyConfiguration.PSObject.Properties.Remove($property)
        Assert-Rejected { Assert-NipatRuntimeBinding $manifest $state $legacyConfiguration } "require setup for legacy configuration without $property"
    }
    $state.PSObject.Properties.Remove('resolved_runtime_image')
    Assert-Rejected { Assert-NipatRuntimeBinding $manifest $state $configuration } 'require setup for an old state without a verified mapping'
    Write-Host "PASS: $assertions scientific-image assertions."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
