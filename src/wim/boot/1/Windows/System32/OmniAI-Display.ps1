$ErrorActionPreference = 'Stop'
$bootOptions = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control').SystemStartOptions
$safeMode = $bootOptions -match '\bOMNIAI_DISPLAY_1024\b'

$source = @'
using System;
using System.Runtime.InteropServices;

public static class OmniAIDisplay
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Device
    {
        public int Size;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Name;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Description;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Id;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Key;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct Address { public long Adapter; public uint Id; }

    [StructLayout(LayoutKind.Explicit, Size = 72)]
    struct DisplayPath
    {
        [FieldOffset(0)] public Address Source;
        [FieldOffset(20)] public Address Target;
    }

    [StructLayout(LayoutKind.Explicit, Size = 64)]
    struct ModeInfo { [FieldOffset(0)] public long Alignment; }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct Request { public uint Type, Size; public long Adapter; public uint Id; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct SourceName
    {
        public Request Header;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Name;
    }

    [StructLayout(LayoutKind.Explicit, Size = 80)]
    struct PreferredMode
    {
        [FieldOffset(0)] public Request Header;
        [FieldOffset(20)] public uint Width;
        [FieldOffset(24)] public uint Height;
    }

    [StructLayout(LayoutKind.Explicit, Size = 220)]
    struct DesktopMode
    {
        [FieldOffset(68)] public ushort Size;
        [FieldOffset(84)] public uint Rotation;
        [FieldOffset(168)] public uint Depth;
        [FieldOffset(172)] public uint Width;
        [FieldOffset(176)] public uint Height;
        [FieldOffset(184)] public uint Refresh;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumDisplayDevices(string device, uint index, ref Device info, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumDisplaySettings(string device, int index, ref DesktopMode mode);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int ChangeDisplaySettingsEx(string device, ref DesktopMode mode, IntPtr window, uint flags, IntPtr parameters);
    [DllImport("user32.dll")]
    static extern int GetDisplayConfigBufferSizes(uint flags, out uint paths, out uint modes);
    [DllImport("user32.dll")]
    static extern int QueryDisplayConfig(uint flags, ref uint paths, [Out] DisplayPath[] entries,
        ref uint modes, [Out] ModeInfo[] modeInfo, IntPtr topology);
    [DllImport("user32.dll")]
    static extern int DisplayConfigGetDeviceInfo(ref SourceName packet);
    [DllImport("user32.dll")]
    static extern int DisplayConfigGetDeviceInfo(ref PreferredMode packet);

    static bool TryPreferredMode(string device, out uint width, out uint height)
    {
        const uint activePaths = 2;
        width = height = 0;
        uint paths, modes;
        if (GetDisplayConfigBufferSizes(activePaths, out paths, out modes) != 0 || paths == 0)
            return false;
        var entries = new DisplayPath[paths];
        if (QueryDisplayConfig(activePaths, ref paths, entries, ref modes, new ModeInfo[modes], IntPtr.Zero) != 0)
            return false;
        for (int index = 0; index < paths; index++)
        {
            var path = entries[index];
            var source = new SourceName { Header = new Request { Type = 1, Size = 84, Adapter = path.Source.Adapter, Id = path.Source.Id } };
            if (DisplayConfigGetDeviceInfo(ref source) != 0 ||
                !String.Equals(source.Name, device, StringComparison.OrdinalIgnoreCase))
                continue;
            var target = new PreferredMode { Header = new Request { Type = 3, Size = 80, Adapter = path.Target.Adapter, Id = path.Target.Id } };
            if (DisplayConfigGetDeviceInfo(ref target) == 0 && target.Width != 0 && target.Height != 0)
            {
                width = target.Width;
                height = target.Height;
                return true;
            }
        }
        return false;
    }

    public static string Apply(bool safe)
    {
        Device primary = new Device();
        for (uint index = 0; ; index++)
        {
            primary.Size = Marshal.SizeOf(typeof(Device));
            if (!EnumDisplayDevices(null, index, ref primary, 0)) return "Primary display unavailable";
            if ((primary.Flags & 4) != 0) break;
        }
        var current = new DesktopMode { Size = 220 };
        if (!EnumDisplaySettings(primary.Name, -1, ref current)) return "Current mode unavailable";
        uint width = 1024, height = 768;
        if (!safe && !TryPreferredMode(primary.Name, out width, out height))
            return String.Format("Preferred mode unavailable; kept {0}x{1}", current.Width, current.Height);
        if (!safe && (current.Rotation & 1) != 0) { uint swap = width; width = height; height = swap; }
        if (current.Width == width && current.Height == height) return String.Format("Already {0}x{1}", width, height);
        var mode = new DesktopMode { Size = 220 };
        for (int pass = 0; pass < 2; pass++)
        {
            for (int index = 0; EnumDisplaySettings(primary.Name, index, ref mode); index++)
            {
                if (mode.Width != width || mode.Height != height || mode.Rotation != current.Rotation ||
                    mode.Depth != current.Depth || (pass == 0 && mode.Refresh != current.Refresh))
                    continue;
                if (ChangeDisplaySettingsEx(primary.Name, ref mode, IntPtr.Zero, 2, IntPtr.Zero) == 0 &&
                    ChangeDisplaySettingsEx(primary.Name, ref mode, IntPtr.Zero, 0, IntPtr.Zero) == 0)
                    return String.Format("Applied {0}x{1}", width, height);
            }
        }
        return String.Format("Mode {0}x{1} unsupported; kept {2}x{3}", width, height, current.Width, current.Height);
    }
}
'@

Add-Type -TypeDefinition $source
$result = [OmniAIDisplay]::Apply($safeMode)
"$(if ($safeMode) { 'Fixed' } else { 'Auto' }): $result" | Set-Content "$env:SystemRoot\Temp\omniai-display.log"
