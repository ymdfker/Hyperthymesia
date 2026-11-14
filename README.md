# Hyperthymesia

给 AI agent 用的长期记忆。接入后，你在 Claude Code、Codex、WorkBuddy、Qoder 里说过的事实、做过的决定、
代码里定下的约定，新开会话时 agent 依然记得，不用再交代一遍。

- 记忆存在你电脑上（`~/.hyperthymesia/`），不上传；密码、密钥会先遮盖。
- 后台自动整理，用你 agent 自己最便宜的模型和额度，约占 agent 花费的 1%–2%。
- 个人的事所有项目通用；每个项目的约定只在该项目里可见。

## 接入步骤（约 3 分钟）

### 第 1 步：安装并接入（一行命令）

把命令末尾的 `claude` 换成你用的 agent：`claude`、`codex`、`workbuddy`、`qoder`；用多个就空格隔开写多个。

**macOS / Linux**：打开“终端”，粘贴执行：

```bash
curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- claude
```

**Windows**：打开 PowerShell，粘贴执行（多个 agent 用逗号隔开，如 `"claude,codex"`）：

```powershell
$env:HY_AGENTS="claude"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
```

不需要安装 Python 或其他环境。

### 第 2 步：按 agent 补一步（没列出的跳过）

| 你用的 agent | 还要做 |
|---|---|
| Claude Code、WorkBuddy | 无 |
| Codex | 在 Codex 里输入 `/hooks`，批准 hyperthymesia |
| Qoder | 按屏幕提示执行一次 `qodercli login` |

### 第 3 步：重启 agent

完全退出再打开。之后正常使用即可，什么都不用管。

### 第 4 步（可选）：检查

```bash
hyperthymesia doctor
```

看到“写入提供方”后面有 agent 名和模型名，就说明接入成功。（提示找不到命令时，用完整路径 `~/.local/bin/hyperthymesia`，Windows 为 `%USERPROFILE%\.hyperthymesia\bin\hyperthymesia.exe`。）

## 可选操作

**让 agent 记得接入之前的聊天**：

```bash
hyperthymesia import --list
hyperthymesia import --agent claude --session 会话编号
```

（`--all --days 7` 导入最近 7 天全部会话；只能补回对话，补不回当时的代码改动。）

**只在某个项目里试用**：`hyperthymesia install claude --project 项目目录`。

**用 API key 整理记忆**（一般不需要：会自动沿用 agent 里已配的 key；只有想让整理走另一个 API 时才配）：
新建 `~/.hyperthymesia/config.toml`，写入：

```toml
[writer]
provider = "openai"                      # 任意 OpenAI 兼容接口
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"         # 只写环境变量名，key 本身放在环境变量里，本工具不保存
```

**卸载**：`hyperthymesia uninstall claude`（还原原配置）。删除 `~/.hyperthymesia/` 即清空全部记忆。

## 常用命令

| 命令 | 作用 |
|---|---|
| `install <agent> [--project 目录]` | 接入 agent（原配置先备份） |
| `uninstall <agent> [--project 目录]` | 移除接入，还原原配置 |
| `doctor` | 自检：用哪个模型整理、是否可用 |
| `context [目录]` | 查看该目录下会注入给 agent 的记忆 |
| `write` | 立即整理积压对话（平时后台自动） |
| `import --list` / `import --agent X --session 编号` | 导入接入前的会话 |

## 它是怎么工作的

每轮开始，钩子把相关记忆注入给 agent（记忆多时只注入目录，agent 通过 MCP 工具按需读取）；每轮结束，记下你的原话、
agent 的最终回复和本轮代码改动；积压够多或会话结束时，后台用该 agent 最便宜的模型整理进 `~/.hyperthymesia/`，
旧值被新值取代时自动失效。代码改动通过独立的影子仓库记录，不碰你的 git 历史；`.env`、私钥等凭据文件不读取。

## 开发

- 只用 Python 标准库；测试：`python3 -m unittest discover -s tests -v`
- 推送到 main 后，GitHub Actions 在各系统上测试、用 PyInstaller 打出单文件并冒烟测试；推送 `v*` 标签时自动发布到 Releases。
