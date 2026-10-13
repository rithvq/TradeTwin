param(
    [int]$TimeoutSeconds = 30,
    [switch]$GuardedDispatch
)

$ErrorActionPreference = "Stop"

function Get-TradeTwinPort([string]$Name, [int]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    $envFile = Join-Path $PSScriptRoot '../.env'
    if (-not $value -and (Test-Path -LiteralPath $envFile)) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match "^\s*$Name\s*=\s*(.+?)\s*$") {
                $value = $Matches[1].Trim('"', "'")
            }
        }
    }
    if (-not $value) { return $Default }
    $port = 0
    if (-not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "Invalid port configuration for $Name"
    }
    return $port
}

$webPort = Get-TradeTwinPort 'WEB_PORT' 3000
$apiPort = Get-TradeTwinPort 'API_PORT' 8000
$shipmentPort = Get-TradeTwinPort 'SHIPMENT_SERVICE_PORT' 8011
$compliancePort = Get-TradeTwinPort 'COMPLIANCE_SERVICE_PORT' 8012
$documentPort = Get-TradeTwinPort 'DOCUMENT_SERVICE_PORT' 8013
$intelligencePort = Get-TradeTwinPort 'INTELLIGENCE_SERVICE_PORT' 8014

$checks = @(
    @{ Name = "Web login"; Url = "http://localhost:$webPort/login"; Contains = "TradeTwin" },
    @{ Name = "API health"; Url = "http://localhost:$apiPort/health"; Contains = '"status":"ok"' },
    @{ Name = "Shipment readiness"; Url = "http://localhost:$shipmentPort/ready"; Contains = '"service":"shipment-service"' },
    @{ Name = "Compliance readiness"; Url = "http://localhost:$compliancePort/ready"; Contains = '"service":"compliance-service"' },
    @{ Name = "Document readiness"; Url = "http://localhost:$documentPort/ready"; Contains = '"service":"document-service"' },
    @{ Name = "Intelligence readiness"; Url = "http://localhost:$intelligencePort/ready"; Contains = '"service":"intelligence-service"' },
    @{ Name = "Sign-in service"; Url = "http://localhost:$webPort/api/auth/providers"; Contains = '"provider"' }
)

$failed = @()

foreach ($check in $checks) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $passed = $false
    $lastError = $null

    while ((Get-Date) -lt $deadline -and -not $passed) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $check.Url -TimeoutSec 5
            $body = [string]$response.Content
            $passed = $response.StatusCode -ge 200 -and
                $response.StatusCode -lt 300 -and
                $body.Contains($check.Contains)
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    }

    if ($passed) {
        Write-Host "[PASS] $($check.Name) $($check.Url)" -ForegroundColor Green
    }
    else {
        $failed += $check.Name
        Write-Host "[FAIL] $($check.Name) $($check.Url) $lastError" -ForegroundColor Red
    }
}

if ($failed.Count -gt 0) {
    throw "Health checks failed: $($failed -join ', ')"
}

if ($GuardedDispatch) {
    $schema = Invoke-RestMethod -Uri "http://localhost:$shipmentPort/openapi.json" -TimeoutSec 10
    $paths = @(
        '/api/v1/consignments/{ident}/compliance-evaluations',
        '/api/v1/consignments/{ident}/dispatch-readiness',
        '/api/v1/consignments/{ident}/dispatch-authorizations',
        '/api/v1/regulations/rule-pack-revisions',
        '/api/v1/compliance-evaluations/{ident}/evidence-manifest'
    )
    foreach ($path in $paths) {
        if ($null -eq $schema.paths.PSObject.Properties[$path]) {
            throw "Phase 4 endpoint missing: $path"
        }
        Write-Host "[PASS] Phase 4 endpoint $path" -ForegroundColor Green
    }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$shipmentPort/api/v1/regulations/rule-pack-revisions" -TimeoutSec 10 | Out-Null
        throw 'Unauthenticated access to the Phase 4 registry was permitted.'
    }
    catch {
        if ([int]$_.Exception.Response.StatusCode -ne 401) { throw }
        Write-Host '[PASS] Phase 4 registry requires authentication' -ForegroundColor Green
    }
}

Write-Host "All TradeTwin health checks passed." -ForegroundColor Green
