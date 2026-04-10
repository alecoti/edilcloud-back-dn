param(
    [string]$DbName = "edilcloud_dn",
    [string]$DbUser = "postgres",
    [string]$DbPassword = "postgres",
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432,
    [switch]$CreateDevSuperuser,
    [string]$AdminEmail = "admin@edilcloud.local",
    [string]$AdminUsername = "admin",
    [string]$AdminPassword = "devpass123"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot "..\\venv\\Scripts\\python.exe"
$envLocalPath = Join-Path $repoRoot ".env.local"
$envExamplePath = Join-Path $repoRoot ".env.example"

if (-not (Test-Path $pythonPath)) {
    throw "Python del workspace non trovato in '$pythonPath'."
}

$null = Get-Command psql -ErrorAction Stop
$null = Get-Command createdb -ErrorAction Stop

$env:PGPASSWORD = $DbPassword

$dbExists = (
    psql -w -h $DbHost -p $DbPort -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName';" |
    Out-String
).Trim()

if ($dbExists -ne "1") {
    createdb -w -h $DbHost -p $DbPort -U $DbUser $DbName
    Write-Host "Database '$DbName' creato." -ForegroundColor Green
} else {
    Write-Host "Database '$DbName' gia esistente." -ForegroundColor Yellow
}

if (-not (Test-Path $envLocalPath) -and (Test-Path $envExamplePath)) {
    Copy-Item $envExamplePath $envLocalPath
    Write-Host ".env.local creato da .env.example." -ForegroundColor Green
}

& $pythonPath manage.py migrate

if ($CreateDevSuperuser) {
    $superuserCount = & $pythonPath manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).count())"
    $normalizedSuperuserCount = (($superuserCount | Select-Object -Last 1) | Out-String).Trim()
    if ($normalizedSuperuserCount -eq "0") {
        $env:DJANGO_SUPERUSER_PASSWORD = $AdminPassword
        & $pythonPath manage.py createsuperuser --noinput --email $AdminEmail --username $AdminUsername
        Write-Host "Superuser locale creato: $AdminEmail / $AdminPassword" -ForegroundColor Green
    } else {
        Write-Host "Esiste gia almeno un superuser, nessuna creazione aggiuntiva." -ForegroundColor Yellow
    }
}
