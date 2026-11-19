$ErrorActionPreference = 'Stop'
$catalogs = @(Get-ChildItem -LiteralPath (Join-Path $env:ProgramFiles 'OmniAI Startup\Driver Catalogs') -Filter '*.cat' -File)
if ($catalogs.Count -eq 0) { throw 'The signed driver catalog package is empty' }

Add-Type @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class OmniAIDriverCatalogs {
    [DllImport("wintrust.dll", SetLastError = true)]
    private static extern bool CryptCATAdminAcquireContext(out IntPtr admin, ref Guid subsystem, uint flags);
    [DllImport("wintrust.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CryptCATAdminAddCatalog(IntPtr admin, string file, string name, uint flags);
    [DllImport("wintrust.dll")]
    private static extern bool CryptCATAdminReleaseCatalogContext(IntPtr admin, IntPtr catalog, uint flags);
    [DllImport("wintrust.dll")]
    private static extern bool CryptCATAdminReleaseContext(IntPtr admin, uint flags);

    public static void Add(string file, string name) {
        Guid subsystem = new Guid("F750E6C3-38EE-11D1-85E5-00C04FC295EE");
        IntPtr admin;
        if (!CryptCATAdminAcquireContext(out admin, ref subsystem, 0))
            throw new Win32Exception();
        try {
            IntPtr catalog = CryptCATAdminAddCatalog(admin, file, name, 0);
            if (catalog == IntPtr.Zero)
                throw new Win32Exception();
            CryptCATAdminReleaseCatalogContext(admin, catalog, 0);
        } finally {
            CryptCATAdminReleaseContext(admin, 0);
        }
    }
}
"@

$failed = $false
foreach ($catalog in $catalogs) {
    try {
        [OmniAIDriverCatalogs]::Add($catalog.FullName, $catalog.Name)
        Write-Output "Registered $($catalog.Name)"
    } catch {
        Write-Warning "Unable to register $($catalog.Name). $_"
        $failed = $true
    }
}

Get-CimInstance -ClassName Win32_PnPEntity -Filter 'ConfigManagerErrorCode = 52' | ForEach-Object {
    pnputil.exe /restart-device $_.PNPDeviceID
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}
if ($failed) { exit 1 }
