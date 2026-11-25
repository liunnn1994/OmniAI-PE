# graphify

- When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else. The skill is at `~/.Codex/skills/graphify/SKILL.md`.

# 内置软件

- 严禁打包 TUI 兼容版、为它创建入口或将其用作回退。
- 新增随镜像分发的软件必须打包为 Edgeless 插件，并通过现有 Edgeless 加载入口接入。打包和配置方法见 [README.md](README.md)。
- Edgeless 的在线插件下载统一通过 EPT 命令提供。保留本地插件加载和 LocalBoost。
