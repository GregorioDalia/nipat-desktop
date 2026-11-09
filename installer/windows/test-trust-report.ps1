. (Join-Path $PSScriptRoot 'write-trust-report.ps1')
$checks = 0
function Assert-Trust([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "Trust inventory test failed: $Message" }
    $script:checks++
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-trust-test-' + [Guid]::NewGuid().ToString('N'))
try {
    $app = Join-Path $temporary 'app'
    $distribution = Join-Path $app '.distribution'
    [IO.Directory]::CreateDirectory($distribution) | Out-Null
    $scriptPath = Join-Path $app 'unsigned.ps1'
    [IO.File]::WriteAllText($scriptPath, 'Write-Output "fixture"')
    $unsigned = Get-NipatTrustFile $scriptPath 'app/unsigned.ps1'
    Assert-Trust ($unsigned.signature_status -ceq 'NotSigned' -and $null -eq $unsigned.signer) 'unsigned script stays unsigned'
    try {
        function Get-AuthenticodeSignature { param([string]$LiteralPath) return [pscustomobject]@{ Status = 'HashMismatch' } }
        $rejected = $false
        try { Get-NipatTrustFile $scriptPath 'app/unsigned.ps1' | Out-Null } catch { $rejected = $true }
        Assert-Trust $rejected 'an invalid signature fails closed'
    } finally { Remove-Item Function:Get-AuthenticodeSignature }
    $native = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $signed = Get-NipatTrustFile $native 'fixture/powershell.exe'
    Assert-Trust ($signed.signature_status -ceq 'Valid' -and $signed.signer.subject) 'actual Windows signature inspected'
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = Join-Path $distribution 'python-3.12.10-embed-amd64.zip'
    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($name in @('python.exe', 'pythonw.exe', 'python312.dll')) {
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $native, $name) | Out-Null
        }
    } finally { $zip.Dispose() }
    [IO.File]::WriteAllText((Join-Path $distribution 'installer-manifest.json'),
        (@{ version = '0.8.20'; source_commit = ('a' * 40) } | ConvertTo-Json))
    $output = Join-Path $temporary 'report.json'
    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    Write-NipatTrustReport $app $native $output
    $report = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    Assert-Trust ($report.files.Count -eq 5 -and $report.counts.Valid -eq 4 -and $report.counts.NotSigned -eq 1) 'stage, setup and archived executables inspected'
    Assert-Trust ($report.smart_app_control.status -ceq 'not-performed' -and $report.assessment -ceq 'unsigned-components-present') 'inventory does not claim SAC acceptance'
    Assert-Trust ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ceq $archiveHash) 'archived executable inspection preserves source bytes'
    Assert-Trust (@(Get-ChildItem -LiteralPath $app -Recurse -Filter '*.exe').Count -eq 0) 'archive inspection leaves no extracted executable in stage'
    $rejected = $false
    try { Write-NipatTrustReport $app $native $output } catch { $rejected = $true }
    Assert-Trust $rejected 'existing evidence is never overwritten'

    # The collector reads bounded event fields only; unrelated XML/command
    # lines and private profile names must not leak into the diagnostic JSON.
    # Mutate a shared observation object. A scalar assigned through $script:
    # inside the mock belongs to the invoked collector's script scope.
    $queryObservation = [pscustomobject]@{ Limit = 0; Calls = 0; Filter = $null }
    function Get-WinEvent {
        param($FilterHashtable, [int]$MaxEvents, $ErrorAction)
        $queryObservation.Limit = $MaxEvents
        $queryObservation.Calls++
        $queryObservation.Filter = $FilterHashtable
        $event = [pscustomobject]@{ Id = 3077; RecordId = 42; TimeCreated = [DateTime]::UtcNow }
        $event | Add-Member -MemberType ScriptMethod -Name ToXml -Value {
            $path = [Security.SecurityElement]::Escape((Join-Path $env:USERPROFILE 'Downloads\NIPAT-Setup.exe'))
            return ('<Event><EventData><Data Name="FileName">' + $path + '</Data>' +
                '<Data Name="ProcessName">\Device\HarddiskVolume3\Users\private-user\app.exe</Data>' +
                '<Data Name="PolicyName">VerifiedAndReputableDesktop</Data>' +
                '<Data Name="PolicyId"></Data>' +
                '<Data Name="CommandLine">private argument</Data></EventData></Event>')
        }
        return $event
    }
    $diagnosticPath = Join-Path $temporary 'diagnostics.json'
    & (Join-Path $PSScriptRoot 'collect-windows-security.ps1') -Hours 2 -MaxEvents 3 -OutputPath $diagnosticPath
    $diagnosticsText = Get-Content -LiteralPath $diagnosticPath -Raw
    $diagnostics = $diagnosticsText | ConvertFrom-Json
    Assert-Trust ($queryObservation.Calls -eq 1 -and $queryObservation.Limit -eq 3) 'collector applies one bounded event query'
    Assert-Trust ($queryObservation.Filter.LogName -ceq 'Microsoft-Windows-CodeIntegrity/Operational' -and
        (@($queryObservation.Filter.Id) -join ',') -ceq '3076,3077' -and
        $queryObservation.Filter.StartTime -gt (Get-Date).AddHours(-3)) 'collector queries only recent CodeIntegrity audit and block events'
    Assert-Trust ($diagnostics.event_query_status -ceq 'available') ("collector retains a successful query: " + $diagnostics.event_query_error)
    Assert-Trust ($diagnostics.events.Count -eq 1) 'collector retains the returned event'
    Assert-Trust ($diagnosticsText -notmatch 'private argument|CommandLine|private-user' -and
        $diagnostics.events[0].fields.FileName.StartsWith('%USERPROFILE%')) 'collector excludes command lines and redacts profile path'
    Assert-Trust ($diagnostics.scope -ceq 'read-only-code-integrity-diagnostics') 'collector identifies its limited scope'
    Assert-Trust ($diagnostics.event_query_status -ceq 'available' -and
        $diagnostics.events[0].fields.PolicyId -ceq '') 'empty XML fields do not discard the event query'
    Remove-Item Function:Get-WinEvent
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
Write-Host "PASS: $checks Windows trust inventory checks."
