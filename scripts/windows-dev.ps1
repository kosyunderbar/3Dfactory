[CmdletBinding()]
param(
    [ValidateSet('setup','build','up','down','status','demo','demo-three','demo-p0','simulator')]
    [string]$Action = 'status',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$SimulatorArgs
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cache = Join-Path $root '.build-cache'
$tools = Join-Path $cache 'windows-tools'
$state = Join-Path $cache 'windows-dev'
$data = Join-Path $state 'postgres-data'
$logs = Join-Path $state 'logs'
$manifest = Get-Content (Join-Path $PSScriptRoot 'windows-tools.json') -Raw | ConvertFrom-Json
foreach ($dir in @($tools,$state,$logs)) { New-Item -ItemType Directory -Force $dir | Out-Null }
function Tool([string]$name) { Join-Path (Join-Path $tools $manifest.$name.directory) $manifest.$name.executable }
function Run([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$exe failed (exit $LASTEXITCODE)" }
}
function Configure {
    foreach ($name in @('node','jdk','python','postgres','maven')) {
        if (!(Test-Path (Tool $name))) { throw 'Tools missing. Run: .\scripts\windows-dev.ps1 setup' }
    }
    $env:JAVA_HOME = Join-Path $tools $manifest.jdk.directory
    # Do not inherit a global DEBUG flag into Spring Boot's development servers.
    $env:DEBUG = 'false'
    $env:PATH = "$(Join-Path $tools $manifest.node.directory);$env:JAVA_HOME\bin;$env:PATH"
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:INGESTION_TCP_HOST = '127.0.0.1'
    $env:INGESTION_TCP_PORT = '9090'
    $env:INGESTION_HTTP_ADDRESS = '127.0.0.1'
    $env:OPERATIONS_HTTP_ADDRESS = '127.0.0.1'
    $env:INGESTION_TCP_ADDRESS = '127.0.0.1'
    $env:OPERATIONS_BASE_URL = 'http://127.0.0.1:8082'
    $env:INGESTION_DIAGNOSTIC_URL = 'http://127.0.0.1:8081'
    $env:OPERATIONS_PROXY_TARGET = 'http://127.0.0.1:8082'
    $env:FACTORY_SIMULATOR_PYTHON = Tool 'python'
    $env:INGESTION_REJECTION_LOG = Join-Path $logs 'rejections.ndjson'
    foreach ($line in Get-Content (Join-Path $root '.env')) {
        if ($line -match '^([A-Z_]+)=(.+)$') { [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process') }
    }
    foreach ($svc in @('INGESTION','OPERATIONS')) {
        $lower = $svc.ToLowerInvariant()
        [Environment]::SetEnvironmentVariable("${svc}_DB_URL","jdbc:postgresql://127.0.0.1:55432/${lower}_db",'Process')
        [Environment]::SetEnvironmentVariable("${svc}_DB_USERNAME","${lower}_app",'Process')
        [Environment]::SetEnvironmentVariable("${svc}_MIGRATION_USERNAME","${lower}_migrator",'Process')
        [Environment]::SetEnvironmentVariable("${svc}_DB_PASSWORD",[Environment]::GetEnvironmentVariable("${svc}_APP_PASSWORD"),'Process')
        [Environment]::SetEnvironmentVariable("${svc}_MIGRATION_PASSWORD",[Environment]::GetEnvironmentVariable("${svc}_MIGRATOR_PASSWORD"),'Process')
    }
    $env:PGPASSWORD = $env:POSTGRES_PASSWORD
}
function Pg([string[]]$arguments) {
    Run (Join-Path $tools 'pgsql/bin/psql.exe') (@('-h','127.0.0.1','-p','55432','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1') + $arguments)
}
function StartDb {
    if (!(Test-Path (Join-Path $data 'PG_VERSION'))) {
        if ((Test-Path $data) -and @(Get-ChildItem $data -Force).Count -gt 0) { throw 'Incomplete DB directory; inspect it manually. No automatic reset.' }
        $pwfile = Join-Path $state 'init-password.txt'
        try {
            [IO.File]::WriteAllText($pwfile, $env:POSTGRES_PASSWORD)
            Run (Join-Path $tools 'pgsql/bin/initdb.exe') @('-D',$data,'-U','postgres','--encoding=UTF8','--locale=C','--auth=scram-sha-256',"--pwfile=$pwfile")
            Add-Content (Join-Path $data 'postgresql.conf') "`nlisten_addresses = '127.0.0.1'`nport = 55432`n"
        } finally { if (Test-Path $pwfile) { Remove-Item -LiteralPath $pwfile } }
    }
    & (Tool 'postgres') status -D $data *> $null
    if ($LASTEXITCODE -ne 0) { Run (Tool 'postgres') @('start','-D',$data,'-l',(Join-Path $logs 'postgres.log'),'-w') }
    $dbs = & (Join-Path $tools 'pgsql/bin/psql.exe') -h 127.0.0.1 -p 55432 -U postgres -d postgres -Atc "SELECT count(*) FROM pg_database WHERE datname IN ('ingestion_db','operations_db')"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect project databases' }
    if ($dbs -eq '0') { Pg @('-f',(Join-Path $root 'infrastructure/postgresql/init-databases.psql')) }
    elseif ($dbs -ne '2') { throw 'Partial database setup. Inspect manually; existing data is preserved.' }
}
function ProcessRecord([string]$name) {
    $file = Join-Path $state "$name.json"
    if (!(Test-Path $file)) { return $null }
    $record = Get-Content $file -Raw | ConvertFrom-Json
    $proc = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($proc -and $proc.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.started -and $proc.Path -eq $record.path) { return $proc }
    return $null
}
function StartApp([string]$name,[string]$exe,[string[]]$arguments,[string]$cwd) {
    if (ProcessRecord $name) { Write-Host "$name already running"; return }
    $proc = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "$name.out.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
    @{id=$proc.Id; started=$proc.StartTime.ToUniversalTime().Ticks.ToString(); path=$proc.Path} | ConvertTo-Json | Set-Content (Join-Path $state "$name.json")
}
function WaitHttp([string]$name,[string]$url) {
    $deadline = (Get-Date).AddSeconds(90)
    do {
        if (!(ProcessRecord $name)) { throw "$name exited. Check $logs" }
        try { if ((Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2).StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$name readiness timeout. Check $logs"
}
function Build {
    foreach ($svc in @('operations-service','ingestion-service')) {
        Push-Location (Join-Path $root "services/$svc")
        try { Run (Tool 'maven') @('-B','--no-transfer-progress',"-Dmaven.repo.local=$cache/maven-repository",'-DskipTests','package') } finally { Pop-Location }
    }
    Push-Location (Join-Path $root 'services/factory-console')
    try {
        Run (Join-Path $tools "$($manifest.node.directory)/npm.cmd") @('ci','--no-audit','--no-fund','--cache',"$cache/npm-cache")
        Run (Join-Path $tools "$($manifest.node.directory)/npm.cmd") @('run','build')
    } finally { Pop-Location }
}
if ($Action -eq 'setup') {
    $downloads = Join-Path $cache 'downloads'
    New-Item -ItemType Directory -Force $downloads | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($name in @('node','jdk','python','postgres','maven')) {
        $complete = Join-Path $tools "$name.complete"
        if ((Test-Path (Tool $name)) -and (Test-Path $complete)) { continue }
        $zip = Join-Path $downloads "$name.zip"
        if (!(Test-Path $zip)) {
            Run 'curl.exe' @('--fail','--location','--retry','2','--output',"$zip.partial",$manifest.$name.url)
            Move-Item -LiteralPath "$zip.partial" -Destination $zip
        }
        if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.$name.sha256) { throw "Checksum mismatch: $zip. Inspect or re-download this archive." }
        $destination = $tools
        if ($name -eq 'python') { $destination = Join-Path $tools 'python'; New-Item -ItemType Directory -Force $destination | Out-Null }
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            foreach ($entry in $archive.Entries) {
                # The database runtime does not need pgAdmin, StackBuilder, headers or HTML manuals.
                if ($name -eq 'postgres' -and $entry.FullName -notmatch '^pgsql/(bin/|lib/|share/|[^/]+\.txt$)') { continue }
                $target = [IO.Path]::GetFullPath((Join-Path $destination $entry.FullName))
                if (!$target.StartsWith(([IO.Path]::GetFullPath($destination) + '\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path' }
                if ($entry.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force $target | Out-Null; continue }
                New-Item -ItemType Directory -Force (Split-Path $target -Parent) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target,$true)
            }
        } finally { $archive.Dispose() }
        Set-Content $complete $manifest.$name.sha256
    }
    # Embeddable Python is sufficient: the simulator has no third-party dependencies.
    [IO.File]::WriteAllLines((Join-Path $tools 'python/python312._pth'),@('python312.zip','.',(Join-Path $root 'services/factory-simulator'),$root,'import site'))
    if (!(Test-Path (Join-Path $root '.env'))) { Run (Tool 'python') @((Join-Path $PSScriptRoot 'create-dev-env.py')) }
    Configure
    Run (Tool 'node') @('--version')
    Run (Tool 'jdk') @('-version')
    Run (Tool 'python') @('--version')
    Run (Join-Path $tools 'pgsql/bin/psql.exe') @('--version')
    Write-Host 'Setup complete. Next: .\scripts\windows-dev.ps1 build; .\scripts\windows-dev.ps1 up'
    exit
}
Configure
switch ($Action) {
    'build' { Build }
    'up' {
        foreach ($entry in @(@('operations',8082),@('ingestion',8081),@('ingestion',9090),@('console',5173))) {
            $listener = Get-NetTCPConnection -LocalPort $entry[1] -State Listen -ErrorAction SilentlyContinue
            if ($listener -and !(ProcessRecord $entry[0])) { throw "Port $($entry[1]) is already occupied by another process" }
        }
        StartDb
        foreach ($entry in @(@('operations','operations-service',8082),@('ingestion','ingestion-service',8081))) {
            $jar = Join-Path $root "services/$($entry[1])/target/$($entry[1])-0.1.0-SNAPSHOT.jar"
            if (!(Test-Path $jar)) { throw 'JAR missing. Run build first.' }
            StartApp $entry[0] (Tool 'jdk') @('-jar',('"'+$jar+'"')) $root
            WaitHttp $entry[0] "http://127.0.0.1:$($entry[2])/readyz"
        }
        $console = Join-Path $root 'services/factory-console'
        StartApp 'console' (Tool 'node') @(('"'+(Join-Path $console 'node_modules/vite/bin/vite.js')+'"'),'--host','127.0.0.1','--port','5173') $console
        WaitHttp 'console' 'http://127.0.0.1:5173'
        Write-Host 'Ready: http://127.0.0.1:5173 (run demo or demo-p0 to generate production data)'
    }
    'down' {
        # Windows Stop-Process on Vite does not terminate its Python child automatically.
        $webRecordFile = Join-Path $state 'web-simulator.json'
        if (Test-Path $webRecordFile) {
            $webRecord = Get-Content $webRecordFile -Raw | ConvertFrom-Json
            $webProc = Get-Process -Id $webRecord.id -ErrorAction SilentlyContinue
            if ($webProc -and $webProc.Path -eq $webRecord.path) {
                $startedMs = ([DateTimeOffset]$webProc.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds()
                if ([Math]::Abs($startedMs - $webRecord.startedAtMs) -lt 2000) { Stop-Process -Id $webProc.Id; Write-Host 'Stopped web simulator' }
            }
        }
        foreach ($name in @('console','ingestion','operations')) {
            $proc = ProcessRecord $name
            if ($proc) { Stop-Process -Id $proc.Id; $proc.WaitForExit(10000) | Out-Null; Write-Host "Stopped $name" }
        }
        if (Test-Path (Join-Path $data 'PG_VERSION')) {
            & (Tool 'postgres') status -D $data *> $null
            if ($LASTEXITCODE -eq 0) { Run (Tool 'postgres') @('stop','-D',$data,'-m','fast','-w') }
        }
        Write-Host 'Stopped. Database files and run history preserved.'
    }
    'status' {
        foreach ($name in @('operations','ingestion','console')) {
            $proc = ProcessRecord $name
            if ($proc) { Write-Host "$name RUNNING (PID $($proc.Id))" } else { Write-Host "$name STOPPED" }
        }
        & (Tool 'postgres') status -D $data
    }
    { $_ -in 'demo','demo-three','demo-p0','simulator' } {
        $arguments = $SimulatorArgs
        if ($Action -eq 'demo') { $arguments = @('--connected-demo') }
        if ($Action -eq 'demo-three') { $arguments = @('--connected-three-demo') }
        if ($Action -eq 'demo-p0') { $arguments = @('--connected-p0-demo') }
        Push-Location (Join-Path $root 'services/factory-simulator')
        try { Run (Tool 'python') (@('-m','factory_simulator') + $arguments) } finally { Pop-Location }
    }
}
