param(
    [string]$ApplicationDirectory,
    [string]$InstallerPath,
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NipatTrustFile {
    param([string]$Path, [string]$RelativePath)
    $file = Get-Item -LiteralPath $Path -Force
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Trust inventory requires a regular file: $RelativePath"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    $status = [string]$signature.Status
    # Unsigned research components remain visible. An invalid signature must
    # never be silently downgraded to an unsigned or trusted component.
    if ($status -cnotin @('Valid', 'NotSigned')) {
        throw "Authenticode validation failed for ${RelativePath}: $status"
    }
    $signer = $null
    if ($status -ceq 'Valid') {
        if ($null -eq $signature.SignerCertificate) { throw "Missing signer: $RelativePath" }
        $signer = [ordered]@{
            subject = $signature.SignerCertificate.Subject
            thumbprint = $signature.SignerCertificate.Thumbprint.ToLowerInvariant()
            public_key_oid = $signature.SignerCertificate.PublicKey.Oid.Value
        }
    }
    return [ordered]@{
        path = $RelativePath
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $file.Length
        signature_status = $status
        signer = $signer
    }
}

function Get-NipatTrustTreeFiles {
    param([string]$Directory)
    # Enumerate explicitly: Get-ChildItem -Recurse can follow a junction before
    # its target is checked. No externally linked content belongs to the stage.
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'A trust inventory cannot traverse reparse points.'
        }
        if ($item.PSIsContainer) { Get-NipatTrustTreeFiles $item.FullName }
        elseif ($item.Extension -iin @('.exe', '.dll', '.pyd', '.ps1', '.psm1')) { $item }
    }
}

function Write-NipatTrustReport {
    param([string]$ApplicationDirectory, [string]$InstallerPath, [string]$OutputPath)
    $app = (Resolve-Path -LiteralPath $ApplicationDirectory).Path.TrimEnd('\', '/')
    $installer = (Resolve-Path -LiteralPath $InstallerPath).Path
    $output = [IO.Path]::GetFullPath($OutputPath)
    if (Test-Path -LiteralPath $output) { throw 'Trust report output already exists.' }
    if ($output.StartsWith($app + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Trust evidence must be written outside the immutable application stage.'
    }
    if ((Get-Item -LiteralPath $app).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'The staged application must not be a reparse point.'
    }
    $manifest = Get-Content -LiteralPath (Join-Path $app '.distribution\installer-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.source_commit -cnotmatch '^[0-9a-f]{40}$' -or
        $manifest.version -cnotmatch '^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$') {
        throw 'Invalid source identity in installer manifest.'
    }
    $files = New-Object 'Collections.Generic.List[object]'
    foreach ($file in Get-NipatTrustTreeFiles $app) {
        $relative = $file.FullName.Substring($app.Length + 1).Replace('\', '/')
        $files.Add((Get-NipatTrustFile $file.FullName ('app/' + $relative)))
    }
    $setup = Get-NipatTrustFile $installer 'setup/NIPAT-Setup.exe'
    $files.Add($setup)

    # Embedded CPython is shipped as a verified ZIP. Inspect its executable
    # members too, without running or modifying them or changing the stage.
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archives = @(Get-ChildItem -LiteralPath (Join-Path $app '.distribution') -Filter 'python-*-embed-amd64.zip' -File)
    if ($archives.Count -ne 1) { throw 'Exactly one embedded CPython archive is required.' }
    $archiveIdentity = [ordered]@{
        path = 'app/.distribution/' + $archives[0].Name
        sha256 = (Get-FileHash -LiteralPath $archives[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $archives[0].Length
    }
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-trust-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    $zip = $null
    try {
        $zip = [IO.Compression.ZipFile]::OpenRead($archives[0].FullName)
        $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $count = 0
        $total = 0L
        foreach ($entry in $zip.Entries) {
            if (-not $seen.Add($entry.FullName) -or $zip.Entries.Count -gt 10000) {
                throw 'Invalid or duplicate embedded CPython archive entries.'
            }
            if ([IO.Path]::GetExtension($entry.FullName) -in @('.exe', '.dll', '.pyd', '.ps1', '.psm1')) {
                if ($entry.FullName -match '(^/|\\|:|(^|/)\.\.?(/|$)|//)') {
                    throw 'Invalid executable archive member path.'
                }
                if ($entry.Length -gt 64MB -or $entry.Length -le 0) { throw 'Invalid executable archive member size.' }
                $total += $entry.Length
                if ($total -gt 256MB) { throw 'Embedded executable inventory exceeds its size limit.' }
                # A generated local name avoids ZIP path traversal entirely.
                $member = Join-Path $temporary (([string]$count) + [IO.Path]::GetExtension($entry.FullName))
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $member, $false)
                $files.Add((Get-NipatTrustFile $member ('app/.distribution/' + $archives[0].Name + '!/' + $entry.FullName)))
                $count++
            }
        }
        if ($count -eq 0) { throw 'Embedded CPython contains no executable files.' }
    } finally {
        if ($null -ne $zip) { $zip.Dispose() }
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
    $orderedFiles = @($files | Sort-Object { $_.path })
    $unsigned = @($orderedFiles | Where-Object { $_.signature_status -ceq 'NotSigned' }).Count
    $report = [ordered]@{
        schema_version = 1
        version = $manifest.version
        source_commit = $manifest.source_commit
        installer_sha256 = $setup.sha256
        scope = 'authenticode-inventory'
        assessment = $(if ($unsigned -gt 0) { 'unsigned-components-present' } else { 'signatures-valid-not-sac-tested' })
        smart_app_control = [ordered]@{ status = 'not-performed' }
        uninstaller = [ordered]@{
            status = 'not-inspected'
            reason = 'Generated during Inno installation; the staged-payload inventory does not execute setup.'
        }
        counts = [ordered]@{ Valid = $orderedFiles.Count - $unsigned; NotSigned = $unsigned }
        embedded_archives = @($archiveIdentity)
        files = $orderedFiles
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $output)) | Out-Null
    [IO.File]::WriteAllText($output, ($report | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
    Write-Host "Authenticode inventory: $($orderedFiles.Count) files, $unsigned unsigned. Smart App Control not tested."
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not $ApplicationDirectory -or -not $InstallerPath -or -not $OutputPath) {
        throw 'ApplicationDirectory, InstallerPath and OutputPath are required.'
    }
    Write-NipatTrustReport $ApplicationDirectory $InstallerPath $OutputPath
}
