# OmniAI PE

OmniAI PE 是基于 HotPE V2.8.251018 的 Windows PE 装配工程。仓库维护版本、ISO 布局、软件和运行时清单，以及可以直接编辑的启动配置。原版 ISO、WIM、驱动、HPM 和其它二进制作为私有构建输入使用。Windows 和原版软件保持原发布形态。

当前默认构建去掉 HotPE 的启动展示窗口、壁纸、主题切换、开始菜单与任务栏透明效果，以及光盘自定义图标。保留开始菜单和任务栏的功能入口、工具快捷方式、HPM 与 Edgeless 加载配置和驱动配置。

## 原版布局

| 内容 | ISO 内位置 | 工程内入口 |
| --- | --- | --- |
| BIOS 和 UEFI | El Torito 目录、`Boot/`、`EFI/` | 构建时复制原版启动镜像与启动文件 |
| 原版 Win11 x64 PE 10.0.26100.5067 | `HotPE/Boot.wim`，映像与启动索引均为 1 | `project.json` 用微软 WinPE 10.0.26100.9974 替换该 WIM |
| 预装软件 | `HotProgMods/*.HPM` | `packages` 和 `media_remove` |
| 外置网卡驱动 | `HotPE/Data/Drives/` | `media` 作用域 |
| 媒体配置 | `HotPE/HotPE.INI`、`HotPE/confi.ini`、`ventoy.dat` | `src/media/` |
| PE 启动、工具菜单和模块加载 | WIM 内 `Windows/Pecmd.ini`、`Program Files/PETools.ini`、`Program Files/HPM/*.WCS` | `src/wim/boot/1/` |

两个 BCD 存储都引用 `\HotPE\Boot.wim` 和 `\Boot\boot.sdi`。原版 PECMD 配置会加载 `PETools.ini`，由它调用 HPM 脚本，扫描 `HotProgMods` 等模块目录。更改 WIM 或目录名称前需要同步处理这些引用。原版文件体积与哈希见 [上游锁](manifests/upstream.lock.json)。

## 本机构建

使用 Windows、[mise](https://mise.jdx.dev/)、[7-Zip](https://www.7-zip.org/) 和 [Windows ADK Deployment Tools](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install)。Python 版本固定在 `.mise.toml`。可用 `OMNIAI_INPUTS` 指定输入目录，默认是 `inputs/`。`SEVENZIP` 和 `OSCDIMG` 可指定工具完整路径。装配涉及 WIM 修改时，在管理员 PowerShell 中执行。

将私有构建包的 HTTPS 地址设为 `OMNIAI_INPUTS_URL`。`mise run fetch-inputs` 下载并校验 [项目配置](manifests/project.json) 引用的输入，再写入尚不存在的输入目录。已有私有 ZIP 时，使用 `mise run fetch-inputs -- --archive 'D:\Downloads\OmniAI-PE-inputs-0.3.24.zip'` 恢复。

```powershell
mise install
mise run fetch-inputs
mise run check
mise run build
```

- `mise run check -- --without-inputs` 只检查清单、配置和路径规则。
- `check` 还校验私有输入以及原版 ISO 的启动镜像。
- `stage` 只装配到 `.work/stage/<version>/media/`，可直接查看拆开的媒体。每次装配都会校验解包出的原版文件，再应用清单。
- `build` 从干净的装配目录生成 ISO 和 SHA-256，输出到 `dist/<version>/`，并校验生成的 ISO 仍包含原版两个启动镜像。

用 `mise tasks ls` 查看所有任务，用 `mise run test` 运行装配脚本的单元测试。

`stage` 和 `build` 都会拒绝覆盖同版本装配目录。重跑时可递增版本，或确认该目录没有活动的 DISM 挂载，同时确认对应的 ISO 没有被测试机使用，再单独处理对应版本的旧目录。DISM 的日志在 `.work/stage/<version>/service-<id>/dism.log`，提交失败时保留对应挂载以供检查。

更新微软 WinPE 底座的流程见 [内核更新与功能装配](ARCHITECTURE.md)。

构建使用微软安装介质中的 Windows PE 索引，以保留微软预装的音频组件。底座来源、哈希和更新步骤见 [底座配方](manifests/base-setup-26100.9974.json) 和 [装配架构](ARCHITECTURE.md)。

启动时会把随附的 `7z.exe` 和 `7z.dll` 复制到 `%SystemRoot%\System32`，以兼容使用原版绝对路径的脚本。

## 增减软件和运行时

编辑 [项目配置](manifests/project.json)。`packages` 每项有 `scope`、`source`、`target` 和 `sha256`。源路径相对于 `inputs/`，目标路径相对于指定作用域的根。作用域 `media` 是 ISO 根，`boot/1` 是 Boot.wim 索引 1 的根。使用同一个入口生成文件或目录的哈希。

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

HotPE 的模块制作、加载行为和授权范围可查阅官方文档。Windows 与随附软件分别遵循各自的授权条款。 [制作 HPM 包](https://docs.hotpe.top/devdoc/makehpm.html) · [模块加载](https://docs.hotpe.top/devdoc/shifthpm.html) · [HotPE 开放授权](https://docs.hotpe.top/cooperation/permit.html)

## 迁移到新版 WinPE

完整 WIM 放入 `inputs/wims/` 后，可在 `wims.boot.replacement` 指定相对于 `inputs/` 的 `source` 和用 `pe.py hash` 得到的 `sha256`。装配先验原版媒体，再替换完整 WIM，校验文件哈希、映像数量和启动索引，最后应用该槽位的包和配置。配置 `kernel_version` 后，装配会在提交 WIM 后读取启动索引的 `ntoskrnl.exe`，版本不匹配时停止打包。迁移时需要更新该槽位的覆盖与删除清单，使其对应新版映像中的实际文件。

可把候选配置放在 `manifests/`，用 `mise run pe -- --manifest candidate.json check` 和 `mise run pe -- --manifest candidate.json build` 验证并构建。替换项的 `windows_packages` 按映像索引列出 CAB/MSU 的 `source` 和 `sha256`，数组顺序就是 DISM 安装顺序。替换项的 `configs` 按索引列出要复制的路径，源文件位于 `src/wim/<id>/<index>/.replacement/`。默认构建跳过这个目录。

微软官方 ADK WinPE 是独立底座。正式切换前需逐项验证启动、工具、模块和驱动。通用 Wi-Fi 是原版 HotPE 的功能之一，微软官方 ADK 不支持通用无线联网，需要独立解决并在真实设备上验证。 [Windows ADK 下载](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install) · [WinPE 可选组件](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe-add-packages--optional-components-reference?view=windows-11)

底座、工具包和整批验收的结构见 [架构说明](ARCHITECTURE.md)。

## GitHub Actions

[流水线](.github/workflows/pe.yml) 在 push 和 PR 时执行源码检查和单元测试。完整构建使用 GitHub 托管的 Windows runner，只在默认分支运行，支持手动触发。设置仓库变量 `OMNIAI_AUTO_BUILD=1` 后，默认分支每次 push 也会执行完整构建。

手动触发和自动构建均使用 `manifests/project.json`，与本地共用 `.mise.toml` 中的任务。

1. 创建 `pe-build` environment 并把部署分支限制为默认分支。
2. 运行 `mise run bundle-inputs`。命令验证私有输入，并将原版 ISO 和项目配置引用的文件及完整目录打入 `.work/bundles/project-<版本>.zip`。把 ZIP 上传到私有存储，再将 runner 可用的 HTTPS 下载地址设为 environment secret `OMNIAI_INPUTS_URL`。
3. 公开仓库还需配置 `OMNIAI_OUTPUT_URL`，例如私有对象的签名 PUT URL，接受 `application/octet-stream`。ISO 会写入该对象，SHA-256 出现在运行摘要。私有仓库通过 Actions artifact 提供 ISO 和校验文件。

签名 URL 要在流水线下载和上传时有效。使用固定 PUT 对象键会覆盖该对象，需要保留历史时按版本更换对象键。
