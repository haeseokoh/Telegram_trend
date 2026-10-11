$ErrorActionPreference = 'Stop'
$taskDesktop = [Environment]::GetFolderPath('Desktop')
$taskName = '텔레그램 트렌드'
$taskPath = Join-Path $taskDesktop ($taskName + '.lnk')
$number = 2
while (Test-Path -LiteralPath $taskPath) {
    $taskPath = Join-Path $taskDesktop ("$taskName ($number).lnk")
    $number++
}
$taskShell = New-Object -ComObject WScript.Shell
$shortcut = $taskShell.CreateShortcut($taskPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'launch_dashboard.ps1') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Description = '텔레그램 채널 종목·이슈·AI 요약 대시보드'
$shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',13'
$shortcut.Save()
Write-Output $taskPath
