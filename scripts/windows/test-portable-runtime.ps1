# Offline checks for verified portable archives and classic/containerd image IDs.
. (Join-Path $PSScriptRoot 'common.ps1')
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
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-portable-' + [Guid]::NewGuid().ToString('N'))
$distribution = Join-Path $temporary '.distribution'
[IO.Directory]::CreateDirectory($distribution) | Out-Null
[IO.Directory]::CreateDirectory((Join-Path $temporary '.runtime')) | Out-Null
$sourceId = 'sha256:' + ('a' * 64)
$localId = 'sha256:' + ('b' * 64)
$calls = New-Object 'Collections.Generic.List[object]'
$images = @{}
$previousImage = $env:NIPAT_RUNTIME_IMAGE

# Only the external Docker command is replaced. Production file verification,
# receipt parsing, image inspection and local runtime selection remain unchanged.
function docker {
    $script:calls.Add(@($args))
    if (($args[0..1] -join '|') -ceq 'image|load') {
        Assert-Test ($args.Count -eq 4 -and $args[2] -ceq '--input' -and $args[3] -ceq $script:archivePath) 'load only the verified archive'
        $global:LASTEXITCODE = $script:loadExitCode
        if ($script:loadExitCode -eq 0) { $script:images[$script:receiptId] = $script:inspection }
        return $script:loadOutput
    }
    if (($args[0..1] -join '|') -ceq 'image|inspect') {
        Assert-Test ($args.Count -eq 3 -and $args[2] -ceq $script:receiptId) 'inspect only the ID from the load receipt'
        if (-not $script:images.ContainsKey($args[2])) {
            $global:LASTEXITCODE = 1
            return
        }
        $global:LASTEXITCODE = 0
        return (ConvertTo-Json -InputObject @($script:images[$args[2]]) -Compress)
    }
    throw 'Unexpected Docker command.'
}

try {
    $archivePath = Join-Path $distribution 'runtime.tar'
    [IO.File]::WriteAllBytes($archivePath, [byte[]]@(1, 2, 3, 4))
    $metadata = [pscustomobject]@{
        schema_version = 1; image_id = $sourceId; os = 'linux'; architecture = 'amd64'
        archive_sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        archive_bytes = 4
    }
    $manifestPath = Join-Path $distribution 'runtime.json'
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $loadExitCode = 0
    foreach ($receiptId in @($sourceId, $localId)) {
        $loadOutput = "Loaded image ID: $receiptId"
        $inspection = [pscustomobject]@{ Id = $receiptId; Os = 'linux'; Architecture = 'amd64' }
        $images.Clear()
        $savedPath = Join-Path $temporary '.runtime/runtime-image.txt'
        if (Test-Path -LiteralPath $savedPath) { Remove-Item -LiteralPath $savedPath }
        # A clean Docker Desktop has neither the image nor an established local
        # mapping. An inherited stale image selection must not change the source.
        $env:NIPAT_RUNTIME_IMAGE = 'sha256:' + ('c' * 64)
        Assert-Test ($images.Count -eq 0 -and $null -eq (Get-NipatImage $receiptId)) 'cold setup starts with zero images and inspect reports missing'
        $calls.Clear()
        Install-NipatRuntime $temporary
        Assert-Test ($calls.Count -eq 2) 'setup verifies load and inspection without selecting a cached image'
        Assert-Test ($images.Count -eq 1 -and $images.ContainsKey($receiptId)) 'embedded archive creates the scientific image in an initially empty store'
        Assert-Test (($calls[0][0..1] -join '|') -ceq 'image|load') 'first setup imports before inspection and never pulls or builds'
        Assert-Test ($env:NIPAT_RUNTIME_IMAGE -ceq $receiptId) 'accept classic or containerd local identity'
        $saved = (Get-Content -LiteralPath (Join-Path $temporary '.runtime/runtime-image.txt') -Raw).Trim()
        Assert-Test ($saved -ceq $receiptId) 'normal launches use the verified local identity'
        Assert-Test ((Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).image_id -ceq $sourceId) 'trusted source identity stays unchanged'
    }

    foreach ($bad in @('', "Loaded image ID: $localId`nLoaded image ID: $sourceId",
        "Loaded image ID: $localId`nLoaded image: other:latest", 'Loaded image: other:latest',
        'Loaded image ID: sha256:abc', "Loaded image ID: $localId`nError unpacking image")) {
        Assert-Rejected { Get-NipatPortableLoadedImageId $bad } 'reject missing, ambiguous, tagged, truncated or failed receipts'
    }
    $receiptId = $localId
    $loadOutput = "Loaded image ID: $receiptId"
    foreach ($inspection in @(
        [pscustomobject]@{ Id = $sourceId; Os = 'linux'; Architecture = 'amd64' },
        [pscustomobject]@{ Id = $localId; Os = 'windows'; Architecture = 'amd64' },
        [pscustomobject]@{ Id = $localId; Os = 'linux'; Architecture = 'arm64' }
    )) {
        Assert-Rejected { Install-NipatRuntime $temporary } 'reject different inspected identity or platform'
    }
    $loadExitCode = 1
    $images.Clear()
    Remove-Item -LiteralPath (Join-Path $temporary '.runtime/runtime-image.txt')
    $calls.Clear()
    Assert-Rejected { Install-NipatRuntime $temporary } 'stop on docker load failure'
    Assert-Test ($calls.Count -eq 1) 'no inspection after a failed import'
    Assert-Test ($images.Count -eq 0 -and -not (Test-Path -LiteralPath (Join-Path $temporary '.runtime/runtime-image.txt'))) 'failed cold import leaves no image or false local mapping'
    $loadExitCode = 0
    [IO.File]::WriteAllBytes($archivePath, [byte[]]@(4, 3, 2, 1))
    $calls.Clear()
    Assert-Rejected { Install-NipatRuntime $temporary } 'reject same-size archive corruption'
    Assert-Test ($calls.Count -eq 0) 'no Docker command for an unverified archive'
    Write-Host "PASS: $assertions portable-runtime assertions."
} finally {
    $env:NIPAT_RUNTIME_IMAGE = $previousImage
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
