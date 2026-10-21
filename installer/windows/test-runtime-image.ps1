# Integration gate: load the ACTUAL exported asset in a fresh dedicated engine
# through both the WSL and Docker Desktop production import paths.
# Linux + Docker + PowerShell only. Does not simulate Windows/WSL/UAC installation.
param(
    [Parameter(Mandatory = $true)][string] $ManifestPath,
    [Parameter(Mandatory = $true)][string] $AssetDirectory,
    [Parameter(Mandatory = $true)][string] $RootfsImage
)
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$manifest = Read-NipatInstallerManifest $ManifestPath
$script:NipatWsl = (Get-Command docker -ErrorAction Stop).Source
$script:NativeInvoke = ${function:Invoke-NipatWsl}
$script:TestContainer = 'nipat-image-test-' + [Guid]::NewGuid().ToString('N')
$script:TestCache = Join-Path ([IO.Path]::GetTempPath()) $script:TestContainer
[IO.Directory]::CreateDirectory($script:TestCache) | Out-Null
$created = $false
$previousImage = $env:NIPAT_RUNTIME_IMAGE

# Adapt only the WSL process boundary to docker exec in the disposable Linux
# rootfs container. Asset verification and image resolution are production code.
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    if (($Arguments[0..4] -join '|') -cne '--distribution|NIPAT-Test|--user|root|--exec') {
        throw 'Unexpected integration-test target.'
    }
    if ($Arguments[5] -ceq 'wslpath') {
        $path = [IO.Path]::GetFullPath($Arguments[-1])
        if ([IO.Path]::GetDirectoryName($path) -cne $script:TestCache) {
            throw 'Archive is outside the verified test cache.'
        }
        return [pscustomobject]@{
            ExitCode = 0; Text = ('/nipat-cache/' + [IO.Path]::GetFileName($path)); ErrorText = ''
        }
    }
    return (& $script:NativeInvoke (@('exec', $script:TestContainer) + $Arguments[5..($Arguments.Length - 1)]) -TimeoutSeconds $TimeoutSeconds)
}
try {
    $created = $true
    # A nested engine cannot unpack overlayfs whiteouts into the outer
    # container's writable layer. Give both data stores fresh host-backed
    # anonymous volumes, as for Docker-in-Docker, and remove only these on exit.
    & $script:NativeInvoke @('run', '--detach', '--name', $script:TestContainer,
        '--privileged', '--cgroupns=host',
        '--mount', 'type=volume,target=/var/lib/docker',
        '--mount', 'type=volume,target=/var/lib/containerd', '--mount',
        ('type=bind,source=' + $script:TestCache + ',target=/nipat-cache,readonly'),
        '--entrypoint', '/bin/sleep', $RootfsImage, 'infinity') -TimeoutSeconds 120 | Out-Null
    $storage = & $script:NativeInvoke @('exec', $script:TestContainer,
        'stat', '-f', '-c', '%T %n', '/var/lib/docker', '/var/lib/containerd')
    Write-Host $storage.Text
    & $script:NativeInvoke @('exec', $script:TestContainer, '/usr/local/bin/nipat-engine', 'ensure') -TimeoutSeconds 240 | Out-Null
    $info = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('info', '--format', '{{.ServerVersion}} {{.Driver}} {{json .DriverStatus}}')
    Write-Host $info.Text
    $initialImages = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('image', 'ls', '--all', '--quiet', '--no-trunc')
    if (-not [string]::IsNullOrWhiteSpace($initialImages.Text)) {
        throw 'The disposable engine must start with zero images.'
    }
    $imageId = Install-NipatScientificImage $manifest $script:TestCache $AssetDirectory 'NIPAT-Test'
    $probe = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('run', '--rm', '--pull=never',
        $imageId, 'sh', '-ec', 'Rscript -e ''stopifnot(requireNamespace("argparse", quietly=TRUE)); cat(R.version.string, "\n")''; samtools --version') -TimeoutSeconds 240
    Write-Host $probe.Text
    $again = Install-NipatScientificImage $manifest $script:TestCache $AssetDirectory 'NIPAT-Test'
    if ($again -cne $imageId) { throw 'Setup resume resolved a different image.' }
    Write-Host "PASS: exported scientific asset loaded, executed and reloaded in the shipped engine: $imageId"

    # Reset only this disposable engine, never the host's Docker Desktop or image
    # store. Delete the exact test image and require an empty inventory afterwards.
    Invoke-NipatRuntimeDocker 'NIPAT-Test' @('image', 'rm', $imageId) | Out-Null
    $emptyImages = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('image', 'ls', '--all', '--quiet', '--no-trunc')
    if (-not [string]::IsNullOrWhiteSpace($emptyImages.Text)) {
        throw 'Docker Desktop cold-import check requires zero images in the disposable engine.'
    }
    Write-Host 'Docker Desktop import check: zero images, no saved local runtime identity.'

    # Reuse the verified bytes as the installed EXE layout without another large
    # copy. The cache and its subdirectories are already mounted read-only into
    # the disposable engine. No registry, user installation or host image changes.
    . (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts/windows/common.ps1')
    $distribution = Join-Path $script:TestCache '.distribution'
    [IO.Directory]::CreateDirectory($distribution) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $script:TestCache '.runtime')) | Out-Null
    $asset = $manifest.assets.scientific_image
    $cachedArchive = Join-Path $script:TestCache ($asset.sha256 + '-' + $asset.file)
    $script:PortableArchive = Join-Path $distribution 'runtime.tar'
    Move-Item -LiteralPath $cachedArchive -Destination $script:PortableArchive
    [ordered]@{
        schema_version = 1; image_id = $manifest.runtime_image
        os = 'linux'; architecture = 'amd64'
        archive_sha256 = $asset.sha256; archive_bytes = $asset.size
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $distribution 'runtime.json') -Encoding UTF8
    $script:PortableDockerCalls = New-Object 'Collections.Generic.List[object]'

    # Replace only the process transport: common.ps1 still verifies the archive,
    # invokes load, parses the actual receipt, inspects the actual image and saves
    # the resolved local ID. Unrelated Docker commands are not permitted here.
    function docker {
        $script:PortableDockerCalls.Add(@($args))
        if (($args[0..1] -join '|') -ceq 'image|load') {
            if ($args.Count -ne 4 -or $args[2] -cne '--input' -or $args[3] -cne $script:PortableArchive) {
                throw 'Portable import did not select the embedded archive.'
            }
            $arguments = @('image', 'load', '--input', '/nipat-cache/.distribution/runtime.tar')
        } elseif (($args[0..1] -join '|') -ceq 'image|inspect' -and $args.Count -eq 3) {
            $arguments = @($args)
        } else { throw 'Unexpected Docker command during portable cold import.' }
        $result = Invoke-NipatRuntimeDocker 'NIPAT-Test' $arguments -TimeoutSeconds 3600
        $global:LASTEXITCODE = $result.ExitCode
        if ($result.ErrorText) { Write-Host $result.ErrorText }
        return $result.Text
    }
    $mapping = Join-Path $script:TestCache '.runtime/runtime-image.txt'
    if (Test-Path -LiteralPath $mapping) { throw 'Cold import must not have a prior local image mapping.' }
    $env:NIPAT_RUNTIME_IMAGE = 'sha256:' + ('f' * 64)
    Install-NipatRuntime $script:TestCache
    $portableImage = (Get-Content -LiteralPath $mapping -Raw).Trim()
    if ($script:PortableDockerCalls.Count -ne 2 -or
        ($script:PortableDockerCalls[0][0..1] -join '|') -cne 'image|load' -or
        $env:NIPAT_RUNTIME_IMAGE -cne $portableImage) {
        throw 'Cold import must load the embedded archive before inspection and retain the resolved image ID.'
    }
    $probe = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('run', '--rm', '--pull=never',
        $portableImage, 'sh', '-ec', 'Rscript -e ''stopifnot(requireNamespace("argparse", quietly=TRUE)); cat(R.version.string, "\n")''; samtools --version') -TimeoutSeconds 240
    Write-Host $probe.Text
    Write-Host "PASS: Docker Desktop production import loaded and executed the embedded archive from zero images: $portableImage"
} finally {
    $env:NIPAT_RUNTIME_IMAGE = $previousImage
    if ($created) {
        & $script:NativeInvoke @('container', 'rm', '--force', '--volumes', $script:TestContainer) -AllowFailure -TimeoutSeconds 60 | Out-Null
    }
    if (Test-Path -LiteralPath $script:TestCache) { Remove-Item -LiteralPath $script:TestCache -Recurse -Force }
}
