param([string]$Package, [switch]$ShowErrors)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$interactive = !$Package
$mutex = New-Object Threading.Mutex($false, 'Local\OmniAI-PE-Edgeless')
$acquired = $false
$stage = Join-Path $env:SystemRoot ('Temp\edgeless-' + [guid]::NewGuid().ToString('N'))
try {
    if ($interactive) {
        $picker = New-Object Windows.Forms.OpenFileDialog
        try {
            $picker.Filter = 'Edgeless (*.7z;*.7zf;*.7zl)|*.7z;*.7zf;*.7zl'
            if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return }
            $Package = $picker.FileName
        } finally { $picker.Dispose() }
    }
    $archive = Get-Item -LiteralPath $Package
    if ($archive.PSIsContainer -or $archive.Extension -notin '.7z', '.7zf', '.7zl') {
        throw 'Select an Edgeless .7z, .7zf or .7zl package.'
    }
    $boost = $archive.Extension -eq '.7zl'
    if ($boost) {
        $disks = [IO.DriveInfo]::GetDrives() | Where-Object {
            $_.IsReady -and $_.Name.TrimEnd('\') -ne $env:SystemDrive -and
                $_.DriveType -in 'Fixed', 'Removable'
        }
        $repo = $disks | ForEach-Object { Join-Path $_.Name 'Edgeless\BoostRepo' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
        if (!$repo) {
            $picker = New-Object Windows.Forms.FolderBrowserDialog
            try {
                $picker.Description = 'Select a local disk for the Edgeless LocalBoost repository.'
                $picker.ShowNewFolderButton = $false
                if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return }
                $disk = [IO.Path]::GetPathRoot($picker.SelectedPath)
            } finally { $picker.Dispose() }
            if ($disk -notin @($disks | ForEach-Object Name)) {
                throw 'Select a writable local disk for LocalBoost.'
            }
            $repo = Join-Path $disk 'Edgeless\BoostRepo'
        }
        try { $acquired = $mutex.WaitOne() }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        foreach ($path in (Split-Path $repo), $repo) {
            if (!(Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
            $directory = Get-Item -LiteralPath $path -Force
            if (!$directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'The LocalBoost repository must be a regular directory.'
            }
        }
        $cached = Join-Path $repo $archive.BaseName
        $stage = Join-Path $repo ('.pending-' + [guid]::NewGuid().ToString('N'))
    }
    $content = $stage
    if ($boost -and (Test-Path -LiteralPath $cached)) {
        $directory = Get-Item -LiteralPath $cached -Force
        if (!$directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The cached LocalBoost plugin must be a regular directory.'
        }
        $content = $cached
    } else {
        $sevenZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
        & $sevenZip x -y "-o$stage" -- $archive.FullName
        if ($LASTEXITCODE) { throw "Extraction failed (7-Zip exit code $LASTEXITCODE)." }
    }

    $root = Split-Path -Parent $PSScriptRoot
    $items = Get-ChildItem -LiteralPath $content -Force
    $reserved = 'plugin_loader', 'plugin_localboost', 'plugin_ept', 'plugin_outdatedcheck', 'dynamic_creator',
                'EasyDown',
                'Edgeless.WCS', 'LoadAsPlugin.reg',
                'LICENSE', 'UPSTREAM.txt'
    if ($items.Name | Where-Object { $_ -in $reserved }) { throw 'The package contains an Edgeless loader path.' }
    if (Get-ChildItem -LiteralPath $content -Recurse -Force -Attributes ReparsePoint) {
        throw 'The package contains a reparse point.'
    }

    $pecmd = Join-Path $env:SystemRoot 'System32\PECMD.exe'
    if ($boost) {
        if ($content -eq $stage) { [IO.Directory]::Move($stage, $cached) }
        $state = Join-Path $env:SystemDrive 'Users\LocalBoost'
        New-Item -ItemType Directory -Path $state -Force | Out-Null
        $counter = Join-Path $state 'Counter.txt'
        if (!(Test-Path -LiteralPath $counter)) { Set-Content -LiteralPath $counter -Value 0 -Encoding ASCII }
        Set-Content -LiteralPath (Join-Path $state 'repoPart.txt') -Value $repo[0] -Encoding ASCII
        Set-Content -LiteralPath (Join-Path $state 'unit.txt') -Value $cached -Encoding Default
        $unit = Join-Path $root 'plugin_localboost\loadUnit.wcs'
        Start-Process -FilePath $pecmd -ArgumentList ('LOAD "' + $unit + '"') -Wait
        return
    }

    try { $acquired = $mutex.WaitOne() }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    foreach ($item in $items) { Copy-Item -LiteralPath $item.FullName -Destination $root -Force -Recurse }
    Push-Location -LiteralPath $root
    try {
        foreach ($script in $items | Where-Object { !$_.PSIsContainer -and $_.Extension -eq '.cmd' }) {
            & (Join-Path $root $script.Name)
            if ($LASTEXITCODE) { throw "$($script.Name) exited with code $LASTEXITCODE." }
        }
        foreach ($script in $items | Where-Object { !$_.PSIsContainer -and $_.Extension -eq '.wcs' }) {
            Start-Process -FilePath $pecmd -ArgumentList ('LOAD "' + (Join-Path $root $script.Name) + '"') -WorkingDirectory $root -Wait
        }
    } finally { Pop-Location }

    # EPT resolves removable plugins through the Edgeless hot-load inventory.
    $name = $archive.BaseName
    $ept = Join-Path $env:SystemDrive 'Users\ept'
    if ($archive.FullName -eq (Join-Path $ept 'pack.7zf')) {
        $name = (Get-Content -LiteralPath (Join-Path $ept 'Name.txt') -Encoding Default -ErrorAction SilentlyContinue |
            Select-Object -First 1)
    }
    if ($name -and $name.Trim() -and $name -notmatch '[<>:"/\\|?*%&!^();]') {
        $name = $name.Trim()
        $inventory = Join-Path $env:SystemDrive 'Users\Plugins_info'
        foreach ($kind in 'Batch', 'Dir', 'File') {
            New-Item -ItemType Directory -Path (Join-Path $inventory $kind) -Force | Out-Null
        }
        $batch = Join-Path $inventory "Batch\$name.txt"
        if (!(Test-Path -LiteralPath $batch)) { New-Item -ItemType File -Path $batch | Out-Null }
        $items | Where-Object PSIsContainer | ForEach-Object Name |
            Set-Content -LiteralPath (Join-Path $inventory "Dir\$name.txt") -Encoding Default
        $items | Where-Object { !$_.PSIsContainer } | ForEach-Object Name |
            Set-Content -LiteralPath (Join-Path $inventory "File\$name.txt") -Encoding Default
        $list = Join-Path $inventory 'List_Hotload.txt'
        if (!(Test-Path -LiteralPath $list) -or $name -notin (Get-Content -LiteralPath $list -Encoding Default)) {
            Add-Content -LiteralPath $list -Value $name -Encoding Default
        }
    }
} catch {
    if ($interactive -or $ShowErrors) { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Edgeless') }
    Write-Error -ErrorAction Continue $_
    exit 1
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Force -Recurse }
}
