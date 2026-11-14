# Hyperthymesia

A long-term memory framework.


通用 agent 长期记忆框架，以 MCP 为载体。前台 agent 只读（快照注入或 MCP 读取工具）；后台写入由程序主导、调用便宜模型，
把已完成轮次（用户原话、最终回复、工作区改动）整理成“对象 + 原子事实”。个人记忆跨项目共享，每个项目有自己的项目库。
只用 Python 标准库；每个平台打包成一个可执行文件。

设计与测试记录：`~/Documents/projects/agent-long-term-memory-design.md`（§25 现行设计，§26 复盘，§27 本代码库规划）。

进度：建设中。第 1 步完成：存储、作用域、脱敏、改动采集；第 2 步写入器已移植，240 轮回归不低于原型；第 3 步读取（快照/目录注入、MCP 只读服务）完成；第 4 步钩子入口、后台写入命令、Claude Code/Codex 安装完成（单元测试），真实宿主端到端待测。

运行测试：`python3 -m unittest discover -s tests -v`

## 构建

每次推送到 main，GitHub Actions 会在 macOS、Windows、Linux 上运行单元测试，用 PyInstaller 打出单个可执行文件 `hyperthymesia`，
并对产物做冒烟测试（MCP 握手、钩子一轮、安装/卸载）。产物在 Actions 的构建记录里下载。
本地打包：`python -m pip install pyinstaller` 后执行 workflow 里的打包命令。PyInstaller 只在构建时需要，产物不依赖它，也不依赖 Python。

## 写入模型配置

写入器需要一个便宜模型。默认自动选择本机已安装的 agent 命令行（codex、claude、qoder、dsh），借用该 agent 自己的登录和额度，
本框架不接触任何 key。要改用 API（如 DeepSeek、OpenAI），在 `~/.hyperthymesia/config.toml` 写：

```toml
[writer]
provider = "openai"
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"   # 只写环境变量名，运行时从环境读取，不保存、不复制 key
```

`hyperthymesia doctor` 检查当前用的是哪个提供方、命令行是否存在、key 是否读得到（不显示 key 内容）。

