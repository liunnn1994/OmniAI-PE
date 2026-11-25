$loader = Join-Path $PSScriptRoot 'Open-Plugin.ps1'
$powershell = Join-Path $PSHOME 'powershell.exe'
$log = Join-Path $env:SystemRoot 'Temp\omniai-edgeless.log'
foreach ($drive in [IO.DriveInfo]::GetDrives()) {
    if (!$drive.IsReady -or $drive.Name.TrimEnd('\') -eq $env:SystemDrive) { continue }
    $bootMedia = Test-Path -LiteralPath (Join-Path $drive.Name 'OmniAIPE\OmniAIPE.INI')
    if ($drive.DriveType -notin 'Removable', 'CDRom' -and !$bootMedia) { continue }
    foreach ($relative in 'EdgelessPlugin', 'Edgeless\Resource') {
        $folder = Join-Path $drive.Name $relative
        if (!(Test-Path -LiteralPath $folder -PathType Container)) { continue }
        Get-ChildItem -LiteralPath $folder -File | Where-Object { $_.Extension -in '.7z', '.7zf', '.7zl' } |
            Sort-Object Name | ForEach-Object {
                & $powershell -NoProfile -ExecutionPolicy Bypass -File $loader -Package $_.FullName *>> $log
            }
    }
}
