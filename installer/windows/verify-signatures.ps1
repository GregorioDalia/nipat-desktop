[CmdletBinding()]
param(
    [string] $SetupPath,
    [string] $LauncherPath,
    [string] $WslHelperPath,
    [string] $UninstallerPath,
    [string] $ExpectedPublisherSubject,
    [string] $SignToolPath,
    [string[]] $AllowedSignerCertificateSha256 = @(),
    [string] $OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NipatSignatureFile([string] $Path, [string] $Role) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "Missing $Role path." }
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item -isnot [IO.FileInfo] -or $item.Length -le 0 -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "The $Role must be a nonempty regular file: $Path"
    }
    return $item
}

function Get-NipatAuthenticodeSignature([string] $Path) {
    return Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
}

function Invoke-NipatSignToolVerification([string] $Tool, [string] $Path) {
    # /pa selects Authenticode policy; /all checks every embedded signature;
    # /tw warns when a signature lacks a timestamp. Warnings fail this gate.
    $verification = & $Tool verify /pa /all /tw $Path 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool verification failed ($LASTEXITCODE) for ${Path}: $($verification -join [Environment]::NewLine)"
    }
}

function Get-NipatCertificateSha256($Certificate) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($Certificate.RawData))).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Test-NipatCertificateEku($Certificate, [string] $Oid) {
    foreach ($extension in $Certificate.Extensions) {
        if ($extension.Oid.Value -ceq '2.5.29.37') {
            foreach ($usage in $extension.EnhancedKeyUsages) {
                if ($usage.Value -ceq $Oid) { return $true }
            }
        }
    }
    return $false
}

function Invoke-NipatSignatureVerification {
    [CmdletBinding()]
    param(
        [string] $SetupPath,
        [string] $LauncherPath,
        [string] $WslHelperPath,
        [string] $UninstallerPath,
        [string] $ExpectedPublisherSubject,
        [string] $SignToolPath,
        [string[]] $AllowedSignerCertificateSha256 = @(),
        [string] $OutputPath
    )

    if ([string]::IsNullOrWhiteSpace($ExpectedPublisherSubject) -or
        $ExpectedPublisherSubject -cne $ExpectedPublisherSubject.Trim()) {
        throw 'An exact, reviewed publisher certificate subject is required.'
    }
    foreach ($pin in $AllowedSignerCertificateSha256) {
        if ($pin -cnotmatch '^[0-9a-f]{64}$') {
            throw 'Certificate pins must be lowercase SHA-256 digests of the DER certificate.'
        }
    }

    $tool = Get-NipatSignatureFile $SignToolPath 'SignTool'
    if ($tool.Name -ine 'signtool.exe') { throw 'SignToolPath must identify signtool.exe from the Windows SDK.' }
    $paths = [ordered]@{
        setup = $SetupPath
        launcher = $LauncherPath
        wsl_helper = $WslHelperPath
        uninstaller = $UninstallerPath
    }
    $files = [ordered]@{}
    $unique = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($role in $paths.Keys) {
        $file = Get-NipatSignatureFile $paths[$role] $role
        if ($file.Extension -ine '.exe') { throw "The $role must be an EXE file." }
        if (-not $unique.Add($file.FullName)) { throw 'Every binary role must identify a separate file.' }
        $files[$role] = $file
    }

    # Never reuse or overwrite previous evidence. Callers choose a new report
    # path for each verification and must honor this command's failure status.
    $reportPath = $null
    if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        $reportPath = [IO.Path]::GetFullPath($OutputPath)
        if (Test-Path -LiteralPath $reportPath) { throw 'The signature evidence output already exists.' }
        if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($reportPath)) -PathType Container)) {
            throw 'The signature evidence output directory must already exist.'
        }
    }

    $records = [ordered]@{}
    foreach ($role in $files.Keys) {
        $file = $files[$role]
        $before = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $signature = Get-NipatAuthenticodeSignature $file.FullName
        if ([string]$signature.Status -cne 'Valid' -or
            [string]$signature.SignatureType -cne 'Authenticode' -or
            $null -eq $signature.SignerCertificate) {
            throw "The $role does not have a valid trusted Authenticode signature."
        }
        $signer = $signature.SignerCertificate
        if ($signer.Subject -cne $ExpectedPublisherSubject) {
            throw "Unexpected publisher for ${role}: $($signer.Subject)"
        }
        if (-not (Test-NipatCertificateEku $signer '1.3.6.1.5.5.7.3.3')) {
            throw "The $role signer certificate does not declare the code-signing EKU."
        }
        $certificateHash = Get-NipatCertificateSha256 $signer
        if ($AllowedSignerCertificateSha256.Count -gt 0 -and
            $AllowedSignerCertificateSha256 -cnotcontains $certificateHash) {
            throw "The $role signer certificate does not match the reviewed certificate pins."
        }
        $timestamp = $signature.TimeStamperCertificate
        if ($null -eq $timestamp -or -not (Test-NipatCertificateEku $timestamp '1.3.6.1.5.5.7.3.8')) {
            throw "The $role requires a timestamp with a time-stamping certificate."
        }
        Invoke-NipatSignToolVerification $tool.FullName $file.FullName
        $after = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($before -cne $after) { throw "The $role changed during signature verification." }
        $records[$role] = [ordered]@{
            file = $file.Name
            sha256 = $after
            size = (Get-Item -LiteralPath $file.FullName).Length
            publisher_subject = $signer.Subject
            signer_certificate_sha256 = $certificateHash
            timestamp_certificate_sha256 = Get-NipatCertificateSha256 $timestamp
        }
    }
    foreach ($role in $files.Keys) {
        $final = (Get-FileHash -LiteralPath $files[$role].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($final -cne $records[$role].sha256) { throw "The $role changed before signature evidence was completed." }
    }
    $report = [ordered]@{
        schema_version = 1
        verification = 'windows-authenticode-and-signtool'
        verified_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        publisher_subject = $ExpectedPublisherSubject
        files = $records
    }
    if ($null -ne $reportPath) {
        # CreateNew prevents a concurrent writer from replacing an existing report.
        $stream = New-Object IO.FileStream($reportPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try {
            $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes(($report | ConvertTo-Json -Depth 6) + [Environment]::NewLine)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally {
            $stream.Dispose()
        }
    }
    return $report
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-NipatSignatureVerification @PSBoundParameters | ConvertTo-Json -Depth 6
}
