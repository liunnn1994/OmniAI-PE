# OmniAI PE

OmniAI PE 是基于 HotPE V2.8.251018 的 Windows PE 装配工程。仓库维护构建配置、启动脚本和已解包的固定资源。固定资源由 Git LFS 管理，微软 WinPE 底座由初始化任务从微软源制备。

当前默认构建去掉 HotPE 的启动展示窗口、壁纸、主题切换、开始菜单与任务栏透明效果，以及光盘自定义图标。保留开始菜单和任务栏的功能入口、工具快捷方式、HPM 与 Edgeless 加载配置和驱动配置。

UEFI 默认入口优先使用 1920×1080，并关闭强制使用固件最高分辨率。PE 启动后会请求 1920×1080。基本显示驱动无法切换 UEFI 模式时，继续使用固件提供的分辨率。启动菜单仍提供固定 1024×768 的入口。

当前 Microsoft WinPE 底座包含 `dwm.exe`，但桌面会话未运行 DWM。在 VirtualBox 中，仅补入原版 HotPE 的 `dwminit.dll` 或同源 Windows 26100.9974 底座中的初始化 DLL，都会触发交互式登录初始化失败。因此发布镜像继续排除该 DLL。

默认镜像用 Firefox 和 Google Chrome 替换 HotPE 自带的 C86 浏览器，入口位于开始菜单的「网络浏览」。网易 UU 远程、向日葵 SOS 和 RustDesk 位于「远程协助」。这些程序随 ISO 放在 `Apps/`，由用户从菜单手动启动。UU 远程首次运行时会通过随附安装包部署到当前 PE 会话的内存盘。向日葵 SOS 用于接受远程协助。

RustDesk 使用官方同版本的 x86 Sciter 构建。

开始菜单的「文件工具」提供 NanaZip、ImageGlass 和 LocalSend，「文档工具」提供 GenOffice 和 MarkText，「AI 工具」提供 WorkBuddy、OpenCode、DeepSeek Harness 和豆包。豆包默认打开官方网页版，镜像也附带官方桌面版在线安装程序。「系统维护」提供 360 系统急救箱 WinPE 专版。

开始菜单「PE 工具 → PixPin 截图」启动 PixPin 3.6.6.0 官方便携版。启动后按 `Ctrl+1` 框选，按 `Ctrl+C` 复制或按 `Ctrl+S` 保存。启动入口将程序复制到当前 WinPE 会话的用户目录，并补齐 Media Foundation 读取组件和 Network List Manager 的 COM 注册。

LocalSend 1.18.2 提供官方 Windows x64 图形版和命令行版。图形版省略 ZIP 中的 `settings.json`，应用把设置写入当前 PE 会话的用户目录。同一 VirtualBox 配置下，原版 HotPE 的图形版成功接收测试文件，当前底座的图形版接收时可能退出。命令行版也可接收，收到请求后按 `Y`，文件保存在当前 PE 用户的 Downloads 目录。两个版本使用同一端口，请分别启动。

GenOffice 的开始菜单入口传入 `--disable-direct-composition`，只影响本次应用启动。更新 GenOffice 时可沿用该入口，并复测新版能否显示 DOCX 正文。在 VirtualBox 的 WinPE 测试中，桌面版可显示测试 DOCX 正文，随附的 `Apps/GenOffice/resources/cli/genoffice.cmd` 也可读取 DOCX。

开始菜单的「开发工具」提供 Zed 1.29.2 和 PowerShell 7.7.0。VirtualBox 的 WinPE 测试中，Zed 能打开文本文件，PowerShell 7 能执行本地脚本。

## 原版布局

| 内容 | ISO 内位置 | 工程内入口 |
| --- | --- | --- |
| BIOS 和 UEFI | El Torito 目录、`Boot/`、`EFI/` | `inputs/boot/` 中的启动镜像和 `inputs/media/` 中的启动文件 |
| 原版 Win11 x64 PE 10.0.26100.5067 | `HotPE/Boot.wim`，映像与启动索引均为 1 | `project.json` 用微软 WinPE 10.0.26100.9974 替换该 WIM |
| 预装软件 | `HotProgMods/*.HPM` | `packages` 和 `media_remove` |
| 浏览器和远程协助 | `Apps/` | `packages` 和 `src/media/HotPE/HotPE.INI` |
| 外置网卡驱动 | `HotPE/Data/Drives/` | `media` 作用域 |
| 媒体配置 | `HotPE/HotPE.INI`、`HotPE/confi.ini`、`ventoy.dat` | `src/media/` |
| PE 启动、工具菜单和模块加载 | WIM 内 `Windows/Pecmd.ini`、`Program Files/PETools.ini`、`Program Files/HPM/*.WCS` | `src/wim/boot/1/` |

两个 BCD 存储都引用 `\HotPE\Boot.wim` 和 `\Boot\boot.sdi`。构建时根据 `project.json` 的 `boot_descriptions` 更新媒体副本中的启动项名称。UEFI 预启动菜单实测会把中文显示成方框，因此菜单使用 ASCII 名称。进入 PE 后，项目的启动提示使用中文。原版 PECMD 配置会加载 `PETools.ini`，由它调用 HPM 脚本，扫描 `HotProgMods` 等模块目录。更改 WIM 或目录名称前需要同步处理这些引用。原版文件体积与哈希见 [上游锁](manifests/upstream.lock.json)。

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

启动时会把随附的 `7z.exe` 和 `7z.dll` 复制到 `%SystemRoot%\System32`，供 Edgeless 等使用旧路径的模块加载脚本调用。开始菜单和文件关联中的旧 7-Zip 图形入口已移除。

## 增减软件和运行时

编辑 [项目配置](manifests/project.json)。`packages` 每项有 `scope`、`source`、`target` 和 `sha256`。源路径相对于 `inputs/`，目标路径相对于指定作用域的根。作用域 `media` 是 ISO 根，`boot/1` 是 Boot.wim 索引 1 的根。使用同一个入口生成文件或目录的哈希。

大型应用可保留官方发布的 `.zip` 或安装包内的 `.7z` 归档。媒体包配置 `unpacked_sha256` 后，装配会校验归档并展开到 `target`，再校验解包目录的哈希。应用从 ISO 直接启动。

```powershell
mise run hash 'packages/MyTool_[PreInstall].HPM'
mise run hash 'runtimes/MyRuntime'
```

| 操作 | 修改方式 |
| --- | --- |
| 加入软件 | 在 `packages` 添加 `media` 项，指向做好的 HPM，目标例如 `HotProgMods/MyTool_[PreInstall].HPM`。快捷方式和启动参数随 HPM 维护。 |
| 移除原版软件 | 把 [上游锁](manifests/upstream.lock.json) 中对应的 `HotProgMods/...` 路径加入 `media_remove`。 |
| 替换原版软件 | 用相同目标路径安装新包。文件覆盖原文件，目录包整体替换目标目录。原版 WIM 菜单若引用该软件，同步修改相应配置。 |
| 加入便携运行时 | 把已准备好的 x64 文件目录放进 `inputs/runtimes/`，为 `boot/1` 添加一项，例如把 `runtimes/MyRuntime` 放到 `Program Files/MyRuntime`。从应用或启动脚本引用实际路径。只由某个程序使用的运行时也可随该 HPM 打包。 |
| 移除 WIM 内容 | 在 `wim_remove.boot` 加入 `1/<WIM 内路径>`。如删除某个软件目录，检查并更新 `PETools.ini` 里的入口。 |

编辑 `src/` 文件时保留其原始编码、BOM 和换行。装配只写回新增或改过的配置，并在复制软件包之后应用这些改动。需要注册表、服务或系统组件的运行时要另行处理其安装条件，目录复制仅负责把准备好的文件放到目标路径。

浏览器和远程协助包的版本记录在 `packages` 的源路径中。更新时从官方来源获取 Windows 包，更新固定资源和包的 SHA-256，并确认对应快捷方式在只读 ISO 上能启动。浏览器使用 Windows x64 稳定版，从 Firefox 完整安装包取 `core`，从 Chrome 企业版 MSI 取 `Chrome-bin`。UU 远程保留官方安装包，其余远程工具使用官方免安装 EXE。 [Firefox](https://www.firefox.com/en-US/releases/) · [Chrome](https://chromeenterprise.google/download/) · [网易 UU 远程](https://uuyc.163.com/download/) · [向日葵 SOS](https://sunlogin.oray.com/news/15493.html) · [RustDesk](https://github.com/rustdesk/rustdesk/releases)

HotPE 的模块制作、加载行为和授权范围可查阅官方文档。Windows 与随附软件分别遵循各自的授权条款。 [制作 HPM 包](https://docs.hotpe.top/devdoc/makehpm.html) · [模块加载](https://docs.hotpe.top/devdoc/shifthpm.html) · [HotPE 开放授权](https://docs.hotpe.top/cooperation/permit.html)

## 迁移到新版 WinPE

更新默认底座时，修改 `wims.boot.replacement.recipe` 指向的配方，并同步调整该槽位的版本与覆盖清单。初始化和最终装配都会检查目标内核版本。也可把经过校验的完整 WIM 放入 `inputs/wims/`，在项目配置中指定 `source` 和 `sha256`。

可把候选配置放在 `manifests/`，用 `mise run pe -- --manifest candidate.json check` 和 `mise run pe -- --manifest candidate.json build` 验证并构建。替换项的 `windows_packages` 按映像索引列出 CAB/MSU 的 `source` 和 `sha256`，数组顺序就是 DISM 安装顺序。替换项的 `configs` 按索引列出要复制的路径，源文件位于 `src/wim/<id>/<index>/.replacement/`。默认构建跳过这个目录。

微软官方 ADK WinPE 是独立底座。正式切换前需逐项验证启动、工具、模块和驱动。通用 Wi-Fi 是原版 HotPE 的功能之一，微软官方 ADK 不支持通用无线联网，需要独立解决并在真实设备上验证。 [Windows ADK 下载](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install) · [WinPE 可选组件](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe-add-packages--optional-components-reference?view=windows-11)

底座、工具包和整批验收的结构见 [架构说明](ARCHITECTURE.md)。

## GitHub Actions

[流水线](.github/workflows/pe.yml) 在 push 和 PR 时执行源码检查和单元测试。完整构建使用 GitHub 托管的 Windows runner，只在默认分支运行，支持手动触发。设置仓库变量 `OMNIAI_AUTO_BUILD=1` 后，默认分支每次 push 也会执行完整构建。

构建任务随仓库检出 Git LFS 资源，运行 `mise run init` 和 `mise run build`。私有仓库通过 Actions artifact 提供 ISO 和校验文件。公开仓库在运行摘要记录 SHA-256，若在 `pe-build` 环境中配置 `OMNIAI_OUTPUT_URL`，流水线还会将 ISO 上传到对应的私有 HTTPS PUT 地址。
