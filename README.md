# OmniAI PE

OmniAI PE 是基于 HotPE V2.8.251018 的 Windows PE 装配工程。仓库维护构建配置、启动脚本和已解包的固定资源。固定资源由 Git LFS 管理，微软 WinPE 底座由初始化任务从微软源制备。

当前默认构建去掉 HotPE 的启动展示窗口、壁纸、主题切换、开始菜单与任务栏透明效果，以及光盘自定义图标。保留开始菜单和任务栏的功能入口、工具快捷方式、Edgeless 加载配置和驱动配置。

UEFI 和传统 BIOS 启动菜单默认等待 8 秒。第一项在 PE 初始化显示驱动后读取主屏推荐分辨率。无法读取或应用时沿用当前显示模式。第二项请求 1024×768。

当前 Microsoft WinPE 底座包含 `dwm.exe`，但桌面会话未运行 DWM。在 VirtualBox 中，仅补入原版 HotPE 的 `dwminit.dll` 或同源 Windows 26100.9974 底座中的初始化 DLL，都会触发交互式登录初始化失败。因此发布镜像继续排除该 DLL。

桌面与任务栏由 WinXShell 5.1.6 提供。单击开始按钮、按 `Win+S` 或打开桌面的「所有工具」即可搜索和分类浏览现有工具快捷方式，包括 Edgeless 插件生成的入口。「常用工具」可固定所选工具，记录保存在当前 PE 会话。按 `Esc` 关闭面板。

按 `Win+E` 或通过任务栏、工具面板中的文件管理器入口打开 Explorer++ 1.4.0，可使用标签页和书签。系统 Explorer `10.0.26100.9974` 仍用于依赖 Windows Shell 的功能入口，例如蓝牙设备窗口。 [WinXShell 更新记录](https://github.com/slorelee/wimbuilder2/blob/668f4f6b2f88150a4ab6e3d3093678f6457acb6a/assets/doc/History.md) · [Explorer++](https://explorerplusplus.com/download)

默认镜像用 Firefox 和 Google Chrome 替换 HotPE 自带的 C86 浏览器，入口位于开始菜单的「网络浏览」。Chrome 158.0.8127.89 在 WinPE 中以关闭 DirectComposition 的方式启动。网易 UU 远程、向日葵 SOS 和 RustDesk 位于「远程协助」。这些程序随 ISO 放在 `Apps/`，由用户从菜单手动启动。UU 远程首次运行时会通过随附安装包部署到当前 PE 会话的内存盘。向日葵 SOS 用于接受远程协助。

RustDesk 使用官方同版本的 x86 Sciter 构建。

开始菜单的「文件工具」提供 NanaZip、ImageGlass 和 LocalSend，「文档工具」提供 GenOffice 和 MarkText，「网络工具」提供 Free Download Manager。「AI 工具」提供 WorkBuddy、OpenCode Desktop、CC Switch、Magpie、DeepSeek Harness 和豆包。豆包使用官方桌面客户端 2.35.12。WorkBuddy 通过系统 `tar.exe` 解包自带的 Node.js，启动器将自带的 Git、Bash 和 Python 路径传给应用。「系统维护」提供 360 系统急救箱 WinPE 专版。 [豆包桌面客户端](https://www.doubao.com/download/desktop) [WorkBuddy](https://www.codebuddy.cn/work/)

桌面和开始菜单的「图吧工具箱 WinUI 3」启动 1.9.1 便携版。WizTree 位于「硬件检测」，BOOTICE 位于「系统维护」。 [图吧工具箱 WinUI 3](https://github.com/luolangaga/tubatools)

桌面和开始菜单「硬盘工具 → DiskGenius」直接启动内置的 DiskGenius 6.2.0.1829 x64。

开始菜单「PE 工具 → PixPin 截图」启动 PixPin 3.6.6.0 官方便携版。启动后按 `Ctrl+1` 框选，按 `Ctrl+C` 复制或按 `Ctrl+S` 保存。启动入口补齐 Network List Manager 的 COM 注册。Media Foundation 读取组件随 Boot.wim 安装，供 PixPin 和其他桌面程序使用。

图吧工具箱、PixPin、GenOffice、MarkText、WorkBuddy、DeepSeek Harness、豆包、PowerShell 7、OpenCode Desktop、CC Switch 和 Magpie 以压缩包随 ISO 提供。首次点击其中一个入口时会提示选一个有足够空间的本地可写目录，并在其下创建 `OmniAI-PE-AppCache`，只展开当前应用。当前 PE 会话会记住选择。重启后选回同一个目录，即可复用通过校验的缓存。缓存文件有变化时，从 ISO 重新展开并保留原目录。浏览器、WizTree、BOOTICE 和内置到 Boot.wim 的 Free Download Manager 可以直接启动。

PE 命令行内置 Python 3.15.2 和 Node.js 26.13.1 LTS。`pip` 默认使用清华 PyPI 镜像，`npm` 默认使用 npmmirror。

LocalSend 1.18.2 提供官方 Windows x64 图形版和命令行版。图形版省略 ZIP 中的 `settings.json`，应用把设置写入当前 PE 会话的用户目录。同一 VirtualBox 配置下，原版 HotPE 的图形版成功接收测试文件，当前底座的图形版接收时可能退出。命令行版也可接收，收到请求后按 `Y`，文件保存在当前 PE 用户的 Downloads 目录。两个版本使用同一端口，请分别启动。

GenOffice 的开始菜单入口传入 `--disable-direct-composition`，只影响本次应用启动。更新 GenOffice 时可沿用该入口，并复测新版能否显示 DOCX 正文。在 VirtualBox 的 WinPE 测试中，桌面版可显示测试 DOCX 正文，应用目录内随附的 `resources/cli/genoffice.cmd` 也可读取 DOCX。

开始菜单的「开发工具」提供 Zed 1.29.3 和 PowerShell 7.7.0。Zed 的启动入口为当前进程关闭 DirectComposition，使编辑器在 WinPE 中显示正文。

## 原版布局

| 内容 | ISO 内位置 | 工程内入口 |
| --- | --- | --- |
| BIOS 和 UEFI | El Torito 目录、`Boot/`、`EFI/` | `inputs/boot/` 中的启动镜像和 `inputs/media/` 中的启动文件 |
| 原版 Win11 x64 PE 10.0.26100.5067 | `HotPE/Boot.wim`，映像与启动索引均为 1 | 成品使用 `OmniAIPE/Boot.wim`，底座为微软 WinPE 10.0.26100.9974 |
| 预装软件 | `Edgeless/Resource/*.7z` 和 `Edgeless/OnDemand/*.7zf` | `packages` 和 `media_remove` |
| 浏览器和远程协助 | `Apps/` | `packages` 和 `src/media/OmniAIPE/OmniAIPE.INI` |
| 外置网卡驱动 | `HotPE/Data/Drives/` | 成品路径为 `OmniAIPE/Data/Drives/` |
| 媒体配置 | `HotPE/HotPE.INI`、`HotPE/confi.ini`、`ventoy.dat` | `src/media/`，其中 `OmniAIPE.INI` 使用带 BOM 的 UTF-8 |
| PE 启动、工具菜单和模块加载 | WIM 内 `Windows/Pecmd.ini`、`Program Files/PETools.ini`、`Program Files/Edgeless/Edgeless.WCS` | `src/wim/boot/1/` |

构建时将 BIOS 和 UEFI 启动项的 `device`、`osdevice` 指向 `\OmniAIPE\Boot.wim`，并按 `boot_descriptions` 更新菜单名称。UEFI 预启动菜单使用 ASCII，进入 PE 后的启动提示使用中文。构建从本地输入直接装配预装的 Edgeless 插件。原版路径与文件哈希见 [上游锁](manifests/upstream.lock.json)。

`mise run init` 从微软 ADK 10.1.28000.3481 提取并校验 x64 无按键提示的 UEFI 光盘引导镜像。该版 ADK 的 x64 `etfsboot.com` 与仓库的 BIOS 引导镜像字节相同。ISO 装配从已校验的 WinPE WIM 提取两种固件对应的 Windows 启动管理器及配套资源。

## 本机构建

使用 Windows、Git LFS、[mise](https://mise.jdx.dev/)、[7-Zip](https://www.7-zip.org/) 和 [Windows ADK Deployment Tools](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install)。拉取仓库后，在项目根目录打开管理员 PowerShell。Python 版本固定在 `.mise.toml`。`OMNIAI_INPUTS` 可指定其他输入目录，默认使用 `inputs/`。`SEVENZIP` 和 `OSCDIMG` 可指定工具完整路径。

```powershell
git lfs pull
mise install
mise run init
mise run check
mise run build
```

- `mise run check -- --without-inputs` 只检查清单、配置和路径规则。
- `init` 校验 Git 中的固定资源，按 [底座配方](manifests/base-setup-26100.9974.json) 读取微软安装介质的 `boot.wim` 区段、下载所需 MSU 并制备 WinPE。有本地微软安装介质时，可用 `mise run init -- --windows-iso <路径>` 复用。
- `check` 还校验固定资源、两份启动镜像和已制备的底座。
- `stage` 只装配到 `.work/stage/<version>/media/`，可直接查看拆开的媒体。每次装配都会校验解包出的原版文件，再应用清单。
- `build` 从干净的装配目录生成 ISO 和 SHA-256，输出到 `dist/<version>/`，并校验 ISO 内的原版 BIOS 引导镜像和锁定的微软 UEFI 引导镜像。

用 `mise tasks ls` 查看所有任务，用 `mise run test` 运行装配脚本的单元测试。

固定资源位于 `inputs/media/`、`inputs/boot/`、`inputs/packages/`、`inputs/registry/` 和 `inputs/updates/26100/optional/`。初始化用的 WIM、MSU 和生成后的底座保存在本机缓存。单独备份固定资源时仍可运行 `mise run bundle-inputs`。

`stage` 和 `build` 都会拒绝覆盖同版本装配目录。重跑时可递增版本，或确认该目录没有活动的 DISM 挂载，同时确认对应的 ISO 没有被测试机使用，再单独处理对应版本的旧目录。DISM 的日志在 `.work/stage/<version>/service-<id>/dism.log`，提交失败时保留对应挂载以供检查。

更新微软 WinPE 底座的流程见 [内核更新与功能装配](ARCHITECTURE.md)。

构建使用微软安装介质中的 Windows PE 索引，以保留微软预装的音频组件。底座来源、哈希和更新步骤见 [底座配方](manifests/base-setup-26100.9974.json) 和 [装配架构](ARCHITECTURE.md)。

启动时会把随附的 7-Zip 26.06 的 `7z.exe` 和 `7z.dll` 复制到 `%SystemRoot%\System32`，供 Edgeless 等使用旧路径的模块加载脚本调用。开始菜单和文件关联中的旧 7-Zip 图形入口已移除。

通过「Edgeless 插件 → 插件管理命令行」在线安装和管理插件。支持 `ept update`、`ept search`、`ept install`、`ept upgrade`、`ept getver` 和 `ept remove`。 [EPT 使用文档](https://wiki.edgeless.top/v2/playground/ept.html)

本地的 `.7z` 和 `.7zf` 插件可通过「Edgeless 插件 → 选择插件加载」打开，也可在资源管理器中右键加载。`.7zl` 使用 LocalBoost 磁盘仓库。PE 启动时会扫描可移动盘、光盘和 PE 介质上的 `EdgelessPlugin` 与 `Edgeless\Resource` 目录。

## 增减软件和运行时

编辑 [项目配置](manifests/project.json)。`packages` 每项有 `scope`、`source`、`target` 和 `sha256`。源路径相对于 `inputs/`，目标路径相对于指定作用域的根。作用域 `media` 是 ISO 根，`boot/1` 是 Boot.wim 索引 1 的根。使用同一个入口生成文件或目录的哈希。

媒体输入可使用 `.zip` 或 `.7z` 归档。配置 `launch.entry` 后，构建会把程序和初始化脚本打包成 `Edgeless/OnDemand/*.7zf`。开始菜单配置用 `@Edgeless:应用目录名@` 引用归档，点击后首次解包到本地可写盘，后续启动复用经 SHA-256 校验的缓存。可执行文件、启动参数和运行库配置随包分发。

```powershell
mise run hash 'packages/MyTool_1.0_OmniAI.7z'
mise run hash 'runtimes/MyRuntime'
```

| 操作 | 修改方式 |
| --- | --- |
| 加入软件 | 在 `packages` 添加 `media` 项，指向做好的 Edgeless 插件，目标例如 `Edgeless/Resource/MyTool_1.0_OmniAI.7z`。快捷方式和启动参数随包维护。 |
| 移除预装插件 | 从 `packages` 删去对应的 Edgeless 包，并删除引用该包的随附快捷方式。 |
| 替换原版软件 | 用相同目标路径安装新包。文件覆盖原文件，目录包整体替换目标目录。原版 WIM 菜单若引用该软件，同步修改相应配置。 |
| 加入便携运行时 | 把已准备好的 x64 文件目录放进 `inputs/runtimes/`，为 `boot/1` 添加一项，例如把 `runtimes/MyRuntime` 放到 `Program Files/MyRuntime`。从应用或启动脚本引用实际路径。只由某个程序使用的运行时也可随该 Edgeless 插件打包。 |
| 移除 WIM 内容 | 在 `wim_remove.boot` 加入 `1/<WIM 内路径>`。如删除某个软件目录，检查并更新 `PETools.ini` 里的入口。 |

项目文本使用 UTF-8 和 LF，已有 UTF-8 BOM 保留。含中文的 `startnet.cmd` 和 UU 远程 `Start.cmd` 使用 CRLF，以兼容 Windows `cmd.exe`。
`inputs/` 是通过 Git LFS 管理的固定构建输入，保留原始字节以通过哈希校验。

装配只写回新增或改过的配置，并在复制软件包之后应用这些改动。需要注册表、服务或系统组件的运行时要另行处理其安装条件，目录复制仅负责把准备好的文件放到目标路径。

浏览器和远程协助包的版本记录在 `packages` 的源路径中。更新时从官方来源获取 Windows 包，更新固定资源和包的 SHA-256，并确认对应快捷方式在只读 ISO 上能启动。浏览器使用 Windows x64 稳定版，从 Firefox 完整安装包取 `core`，从 Chrome 企业版 MSI 取 `Chrome-bin`。UU 远程保留官方安装包，其余远程工具使用官方免安装 EXE。 [Firefox](https://www.firefox.com/en-US/releases/) · [Chrome](https://chromeenterprise.google/download/) · [网易 UU 远程](https://uuyc.163.com/download/) · [向日葵 SOS](https://sunlogin.oray.com/news/15493.html) · [RustDesk](https://github.com/rustdesk/rustdesk/releases)

Edgeless 插件组件来自上游开放源码，来源和许可证见 [Edgeless 组件目录](inputs/packages/Edgeless-plugin-runtime)。 [Edgeless 插件规范](https://wiki.edgeless.top/v2/develop/plugin.html) · [LocalBoost](https://wiki.edgeless.top/v2/playground/localboost.html)

## 迁移到新版 WinPE

更新默认底座时，修改 `wims.boot.replacement.recipe` 指向的配方，并同步调整该槽位的版本与覆盖清单。初始化和最终装配都会检查目标内核版本。也可把经过校验的完整 WIM 放入 `inputs/wims/`，在项目配置中指定 `source` 和 `sha256`。

可把候选配置放在 `manifests/`，用 `mise run pe -- --manifest candidate.json check` 和 `mise run pe -- --manifest candidate.json build` 验证并构建。替换项的 `windows_packages` 按映像索引列出 CAB/MSU 的 `source` 和 `sha256`，数组顺序就是 DISM 安装顺序。替换项的 `configs` 按索引列出要复制的路径，源文件位于 `src/wim/<id>/<index>/.replacement/`。默认构建跳过这个目录。

微软官方 ADK WinPE 是独立底座。正式切换前需逐项验证启动、工具、模块和驱动。通用 Wi-Fi 是原版 HotPE 的功能之一，微软官方 ADK 不支持通用无线联网，需要独立解决并在真实设备上验证。 [Windows ADK 下载](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install) · [WinPE 可选组件](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe-add-packages--optional-components-reference?view=windows-11)

底座、工具包和整批验收的结构见 [架构说明](ARCHITECTURE.md)。

## GitHub Actions

[流水线](.github/workflows/pe.yml) 在 push 和 PR 时执行源码检查和单元测试。完整构建使用 GitHub 托管的 Windows runner，只在默认分支运行，支持手动触发。设置仓库变量 `OMNIAI_AUTO_BUILD=1` 后，默认分支每次 push 也会执行完整构建。

构建任务随仓库检出 Git LFS 资源，运行 `mise run init` 和 `mise run build`。私有仓库通过 Actions artifact 提供 ISO 和校验文件。公开仓库在运行摘要记录 SHA-256，若在 `pe-build` 环境中配置 `OMNIAI_OUTPUT_URL`，流水线还会将 ISO 上传到对应的私有 HTTPS PUT 地址。
