param(
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Web"; Url = "http://localhost:3000"; Contains = "TradeTwin" },
    @{ Name = "API health"; Url = "http://localhost:8000/health"; Contains = '"status":"ok"' },
    @{ Name = "Shipment readiness"; Url = "http://localhost:8011/ready"; Contains = '"service":"shipment-service"' },
    @{ Name = "Compliance readiness"; Url = "http://localhost:8012/ready"; Contains = '"service":"compliance-service"' },
    @{ Name = "Document readiness"; Url = "http://localhost:8013/ready"; Contains = '"service":"document-service"' },
    @{ Name = "Intelligence readiness"; Url = "http://localhost:8014/ready"; Contains = '"service":"intelligence-service"' },
    @{ Name = "Shipment list"; Url = "http://localhost:8011/shipments"; Contains = "[" }
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

Write-Host "All TradeTwin health checks passed." -ForegroundColor Green
