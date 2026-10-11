param(
    [ValidateRange(1,65535)][int]$Port = 8010,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskRuntime = Join-Path $taskRoot '.runtime'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
$taskUrl = "http://127.0.0.1:$Port"
function Get-TaskHealth {
    try {
        $h = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 1
        if ($h.app -eq 'telegram-trend' -and $h.status -eq 'ok') { return $h }
    } catch { }
    return $null
}
function Find-TaskPython {
    $candidates = @((Join-Path $taskRoot '.venv\Scripts\python.exe'))
    $saved = Join-Path $taskRuntime 'python.path'
    if (Test-Path -LiteralPath $saved) { $candidates += (Get-Content -LiteralPath $saved -Raw).Trim() }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    foreach ($command in @('py','python')) {
        if (Get-Command $command -ErrorAction SilentlyContinue) {
            try {
                $found = if ($command -eq 'py') { & py -3 -c 'import sys; print(sys.executable)' } else { & python -c 'import sys; print(sys.executable)' }
                if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath "$found" -PathType Leaf)) { return "$found" }
            } catch { }
        }
    }
    throw 'Python 3.11 이상을 설치하고 README의 의존성 설치를 진행하세요.'
}
$taskMutex = $null
$taskAcquired = $false
try {
    $hasher = [Security.Cryptography.SHA256]::Create()
    $taskHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes("$taskRoot|$Port"))).Replace('-','').Substring(0,20)
    $hasher.Dispose()
    $taskMutex = New-Object Threading.Mutex($false, "Local\TelegramTrend-$taskHash")
    try { $taskAcquired = $taskMutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $taskAcquired = $true }
    if (-not $taskAcquired) { throw '다른 실행 요청이 진행 중입니다. 잠시 후 다시 실행하세요.' }
    $health = Get-TaskHealth
    $started = $false
    if (-not $health) {
        $socket = New-Object Net.Sockets.TcpClient
        try { $occupied = $socket.ConnectAsync('127.0.0.1',$Port).Wait(500) -and $socket.Connected } catch { $occupied = $false } finally { $socket.Dispose() }
        if ($occupied) { throw "포트 $Port 를 다른 앱이 사용하거나 서버가 아직 준비되지 않았습니다. 기존 앱을 확인하세요." }
        $taskPython = Find-TaskPython
        & $taskPython -c 'import fastapi, uvicorn, requests, bs4' 2> (Join-Path $taskRuntime 'dependency-check.log')
        if ($LASTEXITCODE -ne 0) { throw '필요한 Python 패키지가 없습니다. python -m pip install -r requirements.txt 를 실행하세요.' }
        $process = Start-Process -FilePath $taskPython -ArgumentList @('main.py','--port',"$Port") -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRuntime "launch-$Port.stdout.log") -RedirectStandardError (Join-Path $taskRuntime "launch-$Port.stderr.log") -PassThru
        $started = $true
        $timer = [Diagnostics.Stopwatch]::StartNew()
        do {
            $health = Get-TaskHealth
            if ($health) { break }
            if ($process.HasExited) { throw "서버 실행에 실패했습니다. .runtime/launch-$Port.stderr.log 를 확인하세요." }
            Start-Sleep -Milliseconds 250
        } while ($timer.Elapsed.TotalSeconds -lt 60)
        if (-not $health) { throw '서버 준비 시간이 초과되었습니다. 실행 로그를 확인하세요.' }
    }
    if ($Port -eq 8010) { $health.pid | Set-Content -LiteralPath (Join-Path $taskRuntime 'server.pid') }
    if (-not $NoBrowser) { Start-Process $taskUrl }
    $result = [pscustomobject]@{url=$taskUrl;pid=$health.pid;started=$started;browserOpened=(-not $NoBrowser)} | ConvertTo-Json -Compress
    $result | Set-Content -LiteralPath (Join-Path $taskRuntime 'last_launch.json') -Encoding UTF8
    Write-Output $result
} catch {
    if (-not $NoBrowser) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($_.Exception.Message,'텔레그램 트렌드 실행 안내') | Out-Null
    } else { Write-Error $_.Exception.Message }
    exit 1
} finally {
    if ($taskAcquired) { $taskMutex.ReleaseMutex() }
    if ($taskMutex) { $taskMutex.Dispose() }
}
