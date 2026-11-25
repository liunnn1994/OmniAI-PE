# OmniAI PE 内核更新与功能装配

OmniAI PE 的目标是保留 HotPE V2.8.251018 的非美化功能，以微软官方 WinPE 为系统底座。项目沿用 amd64 26100 分支和索引 1，媒体上的 BIOS 和 UEFI 启动项均指向 `OmniAIPE/Boot.wim`。UEFI 光盘引导镜像取自锁定版本的微软 ADK，BIOS 光盘引导镜像与该版 ADK 一致。媒体上的 BIOS 和 UEFI 启动管理器及配套资源取自 WinPE 映像。

## 构建边界

| 层 | 输入与维护位置 | 更新时处理 |
| --- | --- | --- |
| 外置媒体 | `inputs/media/` 与 `inputs/boot/` 保存解包后的固定资源，`upstream.lock.json` 锁定其路径和哈希 | 更新基准资源时同步更新上游锁 |
| Windows 底座 | `mise run init` 按配方从微软端点取得原始 WinPE WIM 和 MSU，并缓存经过校验的底座 | 同分支更新时修改配方 |
| Windows 组件 | 与底座同分支、同架构的 Microsoft CAB/MSU，按依赖顺序列在清单 | 核对适用性，重新装配并检查内核版本 |
| HotPE 功能 | 原版工具以目录包或文件包移植，使用各自哈希；Windows 功能依赖单独维护 | 重用通过验证的工具包，逐项处理缺失的系统依赖 |
| 启动与外观 | `src/wim/boot/1/` 存放脚本和配置；新底座有显式配置清单 | 保留工具入口、快捷方式和硬件初始化；去掉美化入口与资源 |

装配顺序是验原版媒体、替换整份 WIM、离线应用微软包、复制功能包、应用选定配置、提交 WIM、封装 ISO。任何一步失败都使候选构建失败。WIM 只在装配副本上挂载和修改。

[`project.json`](manifests/project.json) 是本地与 CI 共用的构建配置。同分支更新先复用已验收的工具包和启动配置，再核对新底座所需的微软组件、驱动和运行库。

当前构建使用微软 Windows 11 24H2 LTSC 安装介质的 `sources/boot.wim` 索引 1。该 WinPE 已注册 AudioCore 和 AudioDrivers。在管理员 PowerShell 运行初始化任务。原始双索引 WIM 和官方 MSU 来源见 [安装介质底座配方](manifests/base-setup-26100.9974.json)。

```powershell
mise run init
```

每个 MSU 放在独立目录。脚本校验源 WIM 和 MSU 的 SHA-256，用 DISM 将索引 1 导出成单索引可启动 WIM，依序提交更新。核对内核版本后，将底座和本次生成的哈希写入按配方哈希区分的 `.work/kernel/` 缓存。初始化日志保存在对应的 `.work/init-*/service/` 目录。另有 [ADK 底座配方](manifests/base-26100.9974.json) 可用于对照。

更新到下一版时，复制当前配方并修改目标内核版本、输出文件名、适用的检查点与累积更新及其哈希。制备新底座后，将输出路径、SHA-256 和目标 `kernel_version` 写入迁移清单的 `wims.boot.replacement`，递增项目版本，再用迁移清单运行 `check` 和 `build`。构建在完成 WIM 装配后读取启动索引中内核文件的版本，未达到目标版本时停止生成 ISO。GitHub Actions 使用与迁移清单哈希匹配的已制备 WIM。

安装介质底座的程序目录、.NET 和部分 COM 注册仍引用 `X:\$windows.~bt`。迁移清单启用 `relocate_setup_paths`，在装完微软可选组件后，将这些运行路径指向 WIM 的实际目录。改动只写装配副本的注册表字符串，保留原值类型和组件维护元数据。

有官方 WinPE 可选包的功能优先用 DISM 装包。无线、旧版 x86 工具、Explorer 集成等能力有各自的系统依赖，必须同时维护组件来源、启用方式和验收结果。用一个工具的成功运行来判断它自身的兼容性。微软确认原版 ADK WinPE 的可选包须匹配底座架构及版本，且没有通用无线联网支持。 [微软可选组件参考](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe-add-packages--optional-components-reference?view=windows-11) · [微软 WinPE 限制](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe-intro?view=windows-11)

系统功能层使用同分支、同架构的微软 Windows 安装映像作为文件和 INF 来源。用 `scripts/prepare_compat.py` 比较 HotPE、已装好官方可选组件的 WinPE 和单索引的 Windows 安装 WIM，生成按哈希锁定的私有文件包、驱动包和覆盖清单。沿用原版明确列出的旧版运行库，以及微软映像缺少且原版保留了 INF 和目录签名的厂商驱动。构建通过 DISM 登记驱动，补入底座缺少的文件，并在离线注册表副本中补齐指定服务和 Svchost 成员。并行程序集按架构、程序集版本和语言匹配，保留原有 WinSxS 权限。设备枚举由来宾 PnP 执行。覆盖清单里的未匹配项需要逐项核查。

同分支微软安装映像提供无线配置架构、OCR 资源、32 位 ADO/OLE DB 和应用兼容性数据库。底座及安装映像缺少 WMIC 时，从锁定的 HotPE 原版提取命令和配套资源。原版两份 x86 打印驱动的完整包保存在来宾的 `Program Files/OmniAI x86 Driver Packages`，作为可取用文件交付。amd64 驱动继续由 DISM 登记。

更新兼容输入时，把下列三个变量分别设为原版 ISO 解包得到的 `Boot.wim`、已经装好本项目官方可选包的新版 WinPE WIM，以及同版本微软 Windows 安装映像导出的单索引 WIM。

```powershell
mise run prepare-compat $hotpeWim $winpeWithPackages $windowsInstallWim windows-26100-new
```

按 `.work/compat/windows-26100-new/coverage.json` 核对文件、驱动覆盖和哈希，再更新迁移清单对应的 `files` 和 `drivers`。复用原有第三方工具包和启动配置，按 README 的候选构建命令生成新版 ISO。

迁移清单中的 `SOFTWARE` 文件固定为同版本微软安装映像的注册表来源，按清单合并兼容文件对应的程序集索引和 32 位应用的 SMI 设置。更新底座时，按兼容文件的版本核对这些条目。用 `SysWOW64\cmd.exe` 和Edgeless 加载器验证 32 位程序启动及插件装配。

32 位便携工具还通过 Shell 启动子进程。装配时从同一微软注册表输入补齐 32 位 Property System、ShellItem 和 ShellItemArray 三项 COM 注册。验收时分别用 x86 和 x64 探针调用 `ShellExecuteExW`，再从迁移后的 Edgeless 快捷方式实际启动便携工具。

32 位文件保存对话框使用同版本微软映像的 COM、Explorer 文件夹视图和导航注册。验收分别调用传统 `GetSaveFileNameW` 与现代 `IFileSaveDialog`，检查文件列表和目录切换，再用 AIDA64 生成报告、在保存窗口选择路径，并从关机后的测试盘读回文件。

64 位文件夹选择器从同一微软注册表输入补齐 Shell Name Space ListView 的原生 COM 注册。验收检查 `SHBrowseForFolderW` 的新式目录树，并通过 Recuva 的恢复对话框选择目标卷。

安装官方语言包后，构建根据 `windows_features.<索引>.locale` 配置默认界面、键盘和非 Unicode 程序的区域设置。当前槽位沿用原版的简体中文设置。启动脚本在加载工具快捷方式配置后启动 WinXShell 桌面。开始面板按用户和公共的「开始菜单 → 程序」目录读取快捷方式，继续支持 Edgeless 加载器动态添加的工具。任务栏文件管理器和 `Win+E` 通过 WinXShell 打开 Explorer++。

兼容文件层保留 WinPE 原有的桌面初始化机制。对照测试确认，单独加入完整 Windows 的 `System32/dwminit.dll` 就会在进入启动脚本前出现黑屏。文件筛选和装配校验都排除该文件。

完整 Windows 的 `policymanager.dll` 在 WinPE 默认网络初始化之前进入 `System32` 会使流程停在防火墙启动阶段。构建保留该 DLL，启动脚本在 `wpeinit` 返回后才将它放入 `System32`。若底座已提供该文件，则沿用底座副本。

`wpeinit` 完成后，设备启动配置沿用 HotPE 的网络行为，调用 `wpeutil DisableFirewall` 并建立指向 RAM 盘 `X:\Users` 的 `Users` 共享。对照验收在隔离的 VirtualBox 内部网上检查双向通信和共享入口。 [微软 Wpeutil 命令参考](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/wpeutil-command-line-options?view=windows-11)

迁移使用两个 HotPE 自带的签名 Intel RST 版本和 Dell 发布的签名 RST 17.5.9.1040，覆盖 DISM 拒绝登记的两份原 RST INF 列出的 PCI 硬件 ID。驱动包目录的哈希由迁移清单锁定。 [Dell RST 下载和校验值](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=cg84x)

HotPE 的 SRS 驱动包为五个匹配的 Intel VMD 硬件 ID 使用 20.2.6.1025。Intel Core Ultra Series 3 的 VMD 21.1.0.1006 由 DISM 注入 WinPE。SRS 已移除旧版 19.x VMD 和仅供旧硬件使用的 20.2.4.1019 包。 [Intel RST 发布页](https://www.intel.com/content/www/us/en/download/920456/intel-rapid-storage-technology-driver-installation-software-for-intel-core-ultra-series-3-platforms.html)

外置网络驱动包的 Intel 通用无线驱动使用 24.80.0 的两份签名驱动，已移除旧 Intel 通用无线包及其索引。Intel 通用有线驱动使用 31.3 的 Windows 11 x64 签名驱动，由 DISM 注入 WinPE。 [Intel Wi-Fi 发布说明](https://downloadmirror.intel.com/930341/ReleaseNotes_WiFi_24.80.0_IT.pdf) · [Intel 有线驱动](https://www.intel.com/content/www/us/en/download/727998/intel-network-adapter-driver-for-microsoft-windows-11.html?wapkw=i226)

AMD RAID 使用官方 Windows 11 x64 预装驱动 9.3.3.00291，替换 SRS 包里的旧 AMD RAID 分支。Realtek RTL8127 从 Microsoft Update Catalog 注入 1127.31.50.603。 [AMD RAID 下载](https://www.amd.com/en/support/downloads/drivers.html/chipsets/str5/wrx90.html) · [Realtek 驱动目录](https://www.catalog.update.microsoft.com/ScopedViewInline.aspx?updateid=fb7bc5d7-4f5c-4118-8de1-ebe99fca6ec9)

随完整 Windows 提供的部分驱动由系统组件目录签名。更新兼容包时，按驱动文件哈希查询签名目录，核对签名和 WinPE 已有目录，将缺少的微软签名目录放进迁移清单指定的私有目录包并更新目录哈希。启动脚本在 `wpeinit` 后登记这些目录，并重新启动报告 Code 52 的设备。迁移清单使用安装介质 WinPE 原有的 AudioCore、AudioDrivers、音频服务和访问权限。 [微软目录登记 API](https://learn.microsoft.com/en-us/windows/win32/api/mscat/nf-mscat-cryptcatadminaddcatalog)

旧版程序的 WinMM 音频依赖由同版本微软安装映像提供。文件层保留原版所需的 `.drv` 和 `.acm` 文件，注册表层合并 64 位和 32 位 `Drivers32` 映射。验收用系统声音面板确认默认扬声器，并用 WinMM 播放 WAV。 [微软 WinMM 组件说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/user-mode-wdm-audio-components)

GitHub Actions 的手动触发和启用后的 push 构建使用 `project.json`，通过 Git LFS 取得固定资源，再使用与本地相同的初始化任务制备底座。

## 迁移验收

先完成装配和离线校验，再在 VMware Workstation 中集中验证成品启动。迁移以原版非美化内容的保留、微软底座和驱动与系统依赖的纳入情况为验收范围。内置软件的逐项功能测试和缺陷修复另行安排。

| 验收范围 | 需要的证据 |
| --- | --- |
| BIOS、UEFI、内核、默认外观 | 两种固件下实测启动、来宾版本、桌面和菜单截图 |
| 桌面与工具入口 | 对照原版核对保留的快捷方式和热键，以及移除的美化配置 |
| Edgeless | 核对已有外置应用和上游模块转换后的包内容、初始化脚本和快捷方式 |
| 驱动与系统依赖 | 从交付镜像核对驱动家族、外置驱动包和非标准 WinPE 依赖 |

默认 VirtualBox 测试机断网且无硬盘。优先复用专用测试机和现有测试盘，按用例换挂载。涉及磁盘写入的验证使用独立的测试盘。需要特定物理硬件的用例保留实际设备验证项。每轮清单、版本、结果与截图保存在该版本的 `dist/` 目录。
