# Hyperthymesia

[English user guide](#english-user-guide) · [GitHub](https://github.com/ymdfker/Hyperthymesia) · [AtomGit](https://atomgit.com/ynndfker/Hyperthymesia)

给 AI agent 用的长期记忆。接入后，你在 Claude Code、Codex、WorkBuddy、Qoder、DeepSeek Harness 里说过的事实、做过的决定、
代码里定下的约定，新开会话时 agent 依然记得，不用再交代一遍。

- 记忆库存在你电脑上（`~/.hyperthymesia/`）；后台整理时，相关材料会发送给宿主使用的模型，密码、密钥先做遮盖。
- 后台自动整理，用你 agent 自己最便宜且通过能力检查的模型和额度；额外花费取决于对话和宿主，尚无一周真实使用数据，不承诺固定比例。
- 个人的事所有项目通用；每个项目的约定只在该项目里可见。

## 接入步骤

找到你用的 agent，只按那一节一步步做。用多个 agent 就每一节各做一遍。

当前发行版为 **v0.2.5**，包含WorkBuddy桌面接入、防递归、后台选模和建议保存规则修复。下面的一键命令从GitHub最新发行版安装。macOS命令行已做兼容测试；IDE／桌面完整验收和Windows真实安装链路尚未全部完成。

- [Claude Code](#claude-code)
- [Codex](#codex)
- [WorkBuddy](#workbuddy)
- [Qoder](#qoder)
- [DeepSeek Harness（dsh）](#deepseek-harnessdsh)

不需要安装 Python 或其他环境。

### Claude Code

**1. 安装并接入**

- **Mac / Linux**：打开“终端”（Mac：按 `Command + 空格`，输入“终端”回车），复制下面整行，粘贴进去，按回车：

  ```bash
  curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- claude
  ```

- **Windows**：在开始菜单搜索“PowerShell”并打开，复制下面整行，粘贴进去，按回车：

  ```powershell
  $env:HY_AGENTS="claude"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
  ```

看到“完成”字样即可。

**2. 重启 Claude Code**

完全退出 Claude Code（关掉所有窗口或终端里的 claude），再重新打开。

**3. 检查（可选）**

新开一个终端（或 PowerShell），执行：

```bash
hyperthymesia doctor --agent claude
```

“写入提供方”应显示 `claude`。这只确认整理提供方；还需要确认 MCP 已连接、钩子实际触发。完整检查步骤见[兼容核查清单](docs/desktop-compat.md)。

### Codex

**1. 安装并接入**

- **Mac / Linux**：打开“终端”（Mac：按 `Command + 空格`，输入“终端”回车），复制下面整行，粘贴进去，按回车：

  ```bash
  curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- codex
  ```

- **Windows**：在开始菜单搜索“PowerShell”并打开，复制下面整行，粘贴进去，按回车：

  ```powershell
  $env:HY_AGENTS="codex"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
  ```

看到“完成”字样即可。

**2. 重启 Codex**

完全退出 Codex，再重新打开。

**3. 批准钩子**

在 Codex 输入框里输入 `/hooks` 回车，在列表里找到 hyperthymesia，选择批准（信任）。
不批准的话 Codex 不会运行它，记忆不会生效。

**4. 检查（可选）**

新开一个终端（或 PowerShell），执行：

```bash
hyperthymesia doctor --agent codex
```

“写入提供方”应显示 `codex`。这只确认整理提供方；还需要确认 MCP 已连接、钩子实际触发。完整检查步骤见[兼容核查清单](docs/desktop-compat.md)。

### WorkBuddy

**桌面版已知局限（本机5.3.14实测）**：退出时结束钩子不能可靠送达，未达到批量阈值的尾部可能要等下次进入会话、触发启动钩子后才自动补写。仅打开应用停在首页不保证触发；补写完成前，新会话可能答不出尾部信息。已入库记忆的读取不受此问题直接影响。暂不增加补丁，详见[兼容记录](docs/desktop-compat.md)。

**桌面验证范围**：后台整理曾被自身钩子记录并引发递归；v0.2.5已加入统一内部任务隔离。之后独立桌面短测的核心事实写入和跨会话召回7/7正确，但存在后台耗时及模型选择偏差，整体仅部分通过。新的选模和建议保存规则已完成无模型检查，尚未重新做付费端到端质量验收；退出尾写的宿主局限见上文。详见[兼容报告](docs/desktop-compat.md)。

**发布状态：v0.2.5已包含桌面配置入口修复，下列一键安装或升级命令可安装该版本。**

**1. 安装并接入**

- **Mac / Linux**：打开“终端”（Mac：按 `Command + 空格`，输入“终端”回车），复制下面整行，粘贴进去，按回车：

  ```bash
  curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- workbuddy
  ```

- **Windows**：在开始菜单搜索“PowerShell”并打开，复制下面整行，粘贴进去，按回车：

  ```powershell
  $env:HY_AGENTS="workbuddy"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
  ```

看到“完成”字样即可。

**2. 重启 WorkBuddy**

完全退出 WorkBuddy（Mac：菜单栏 WorkBuddy → 退出；Windows：右下角托盘图标右键 → 退出），再重新打开。

**3. 检查（可选）**

新开一个终端（或 PowerShell），执行：

```bash
hyperthymesia doctor --agent workbuddy
```

“写入提供方”应显示 `codebuddy`（WorkBuddy 内置的就是 CodeBuddy）。这只检查整理配置；还要在 WorkBuddy 的 MCP 设置里确认 `hyperthymesia` 连接成功。

桌面版配置写入 `~/.workbuddy/settings.json` 和 `~/.workbuddy/mcp.json`，原文件会先备份；已有 CodeBuddy CLI 配置保留。若要单独给 CLI 接入，执行 `hyperthymesia install codebuddy`。

上述桌面路径从v0.2.5起生效；v0.2.4旧版使用的是CLI入口。已安装旧版的用户请重新执行第1步升级，再重启WorkBuddy。

### Qoder

**1. 安装并接入**

- **Mac / Linux**：打开“终端”（Mac：按 `Command + 空格`，输入“终端”回车），复制下面整行，粘贴进去，按回车：

  ```bash
  curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- qoder
  ```

- **Windows**：在开始菜单搜索“PowerShell”并打开，复制下面整行，粘贴进去，按回车：

  ```powershell
  $env:HY_AGENTS="qoder"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
  ```

看到“完成”字样即可。

**2. 登录 qodercli**

安装时会自动装好 Qoder 官方命令行 qodercli（整理记忆要用它，用的是你自己的 Qoder 额度）。
在终端里执行下面一行，浏览器会打开 Qoder 登录页，登录并授权即可：

```bash
qodercli login
```

如果安装时提示“需要 npm”：先到 <https://nodejs.org> 下载安装 Node.js（选 LTS 版），然后重新执行第 1 步。

**3. 重启 Qoder**

完全退出 Qoder，再重新打开。

**4. 检查（可选）**

新开一个终端（或 PowerShell），执行：

```bash
hyperthymesia doctor --agent qoder
```

“写入提供方”应显示 `qoder`。这只确认整理提供方；还需要确认 MCP 已连接、钩子实际触发。完整检查步骤见[兼容核查清单](docs/desktop-compat.md)。

### DeepSeek Harness（dsh）

**1. 安装并接入**

- **Mac / Linux**：打开“终端”（Mac：按 `Command + 空格`，输入“终端”回车），复制下面整行，粘贴进去，按回车：

  ```bash
  curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- dsh
  ```

- **Windows**：在开始菜单搜索“PowerShell”并打开，复制下面整行，粘贴进去，按回车：

  ```powershell
  $env:HY_AGENTS="dsh"; irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
  ```

看到“完成”字样即可。

**2. 确认 dsh 已填 DeepSeek API key**

整理记忆用的是你在 dsh 里配置的 DeepSeek key（自动选最便宜的模型）。如果还没填过：
在终端执行 `dsh web`，在打开的页面里进入 设置 → 模型，在 DeepSeek 一栏填入你的 API key（在 <https://platform.deepseek.com> 申请）并保存。

**3. 重启 DeepSeek Harness（dsh）**

在运行 `dsh web` 的终端里按 `Ctrl + C` 关掉它，再重新执行 `dsh web`。

**4. 检查（可选）**

新开一个终端（或 PowerShell），执行：

```bash
hyperthymesia doctor --agent dsh
```

“写入提供方”应显示 `dsh`。这只确认整理提供方；还需要确认 MCP 已连接、钩子实际触发。完整检查步骤见[兼容核查清单](docs/desktop-compat.md)。

### 遇到问题

- **提示找不到 hyperthymesia 命令**：关掉终端重新打开再试；还不行就用完整路径：Mac/Linux 为 `~/.local/bin/hyperthymesia`，
  Windows 为 `%USERPROFILE%\.hyperthymesia\bin\hyperthymesia.exe`。
- **Mac 提示“无法验证开发者”**：系统设置 → 隐私与安全性 → 点“仍要打开”。
- **想看记下了什么**：正常聊几轮后执行 `hyperthymesia context 项目目录`。记忆在后台整理，聊得够多或会话结束时才写入，不会马上出现。

## 可选操作

**让 agent 记得接入之前的聊天**：

```bash
hyperthymesia import --list
hyperthymesia import --agent 你的agent --session 会话编号
```

（`--all --days 7` 导入最近 7 天全部会话；只能补回对话，补不回当时的代码改动。）

**只在某个项目里试用**：`hyperthymesia install 你的agent --project 项目目录`（支持 claude、codex、codebuddy、workbuddy、qoder）。dsh 按 profile 接入，不提供项目级安装隔离。

**用 API key 整理记忆**（一般不需要：会自动沿用 agent 里已配的 key；只有想让整理走另一个 API 时才配）：
新建 `~/.hyperthymesia/config.toml`，写入：

```toml
[writer]
provider = "openai"                      # 任意 OpenAI 兼容接口
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"         # 只写环境变量名，key 本身放在环境变量里，本工具不保存
```

**升级**：重新执行你那一节第 1 步的命令即可（会覆盖程序并重新接入，记忆保留）。

**卸载**：`hyperthymesia uninstall 你的agent`（移除本工具配置，保留其他条目；备份用于需要时手动恢复）。删除 `~/.hyperthymesia/` 即清空全部记忆。

## 常用命令

| 命令 | 作用 |
|---|---|
| `install <agent> [--project 目录]` | 接入 agent（原配置先备份） |
| `uninstall <agent> [--project 目录]` | 移除本工具配置，保留其他条目 |
| `doctor [--agent X]` | 查看整理提供方和模型；不证明钩子、MCP、召回全链路通过 |
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


## IDE 与桌面版验证

各界面的配置路径、接入缺口、简短操作清单及项目覆盖钩子的行为，见 [IDE／桌面兼容核查](docs/desktop-compat.md)。CLI 已通过不等于桌面版已通过；WorkBuddy 桌面配置入口与内置 CLI 默认入口不同，源码已分开适配，桌面短测核心事实写入与召回已通过，耗时、模型偏差和退出尾写局限见兼容记录；不代表全部GUI分支已验收。


## 当前验证结果与待办

配置文件存在、doctor 显示提供方、MCP 连通，分别只证明对应环节；都不能单独证明记忆完整接入。详细步骤、证据和版本见[兼容核查](docs/desktop-compat.md)。

### 项目配置覆盖／禁用钩子（S9）

以下检查未提交模型问答任务，不消耗模型额度。

| 宿主 | 已验证 | 仍未验证或发现的问题 |
| --- | --- | --- |
| Claude Code CLI | 用户与项目启动钩子合并；项目空表不清除用户钩子；项目禁用能阻止启动钩子 | 不能据此覆盖所有 GUI 与生命周期事件 |
| Qoder CLI | 合并通过；两种禁用方式均在正常状态栏下不触发启动钩子，重新开启恢复 | 不等于 IDE 与所有事件已完整验收 |
| WorkBuddy 内置 CLI（桌面配置目录） | 合并、MCP 握手及轮次记录通过；已定位关闭失效的根因 | **本机 5.3.14 内置执行器未检查 disableAllHooks**；七类事件派发代码回放均忽略此键，桌面两轮写入及新会话召回核心事实7/7；快捷验收仅部分通过（详见兼容记录） |
| Codex | 无模型固定 HTTP 响应验证开→关→再开；提交／停止实际记录为 1→0→1 | 不代表全部事件和 GUI 已通过；新钩子仍须审核信任 |
| dsh | 独立 profile 的合成配置确认显式 --patch 能禁用条目；项目目录单放补丁不会自动加载 | 不等于全部运行事件测试通过 |

### 尚未完成

- **一周真实使用**：正常工作中观察记错、漏记、多记及注入量，每隔两三天检查记忆库和整理日志。目前没有长期实用结论。
- **GUI 完整验收**：Claude VS Code／JetBrains／Desktop Code、Codex IDE／App、Qoder IDE／JetBrains、CodeBuddy IDE、WorkBuddy 桌面及 dsh TUI；不能沿用 CLI 或 dsh web 的通过结论。每种形态的简短操作见兼容清单。
- **S9 环境缺项**：独立 CodeBuddy IDE 本机未安装，仍无实机结果。Qoder 禁用、Codex 提交／停止已补验。WorkBuddy 开关失效已归为宿主已知问题，不列为记忆服务待修复项，不增加补丁；它影响用户停用钩子，不妨碍正常开启时的记忆流程，也不能代替桌面完整读写验收。详细证据见[兼容报告 §6](docs/desktop-compat.md#6-s9-剩余项收尾与-workbuddy-根因2026-11-15最新结果)。
- **Windows 端到端**：已有单元测试与 CI，尚未验证真实一键安装、宿主钩子触发、记录和注入。可先用假整理模型做不耗额度的 Windows 集成测试。
- **后续发布验收**：v0.2.5已发布本轮源码修复；构建、打包检查不等于真实桌面或Windows端到端全部通过，仍需按上面的范围继续验收。

可选后续：v0.2.4 全量回归、Gitee 附件匿名下载验证。无用的本地／远端 v0.2.0 标签已删除。任何需要正常模型回合的测试，执行前先报额度预估。


---

## English user guide

Hyperthymesia gives AI agents long-term memory across chats. It captures facts, decisions, project conventions and code changes, then makes relevant memories available in later conversations.

- Memories are stored locally in `~/.hyperthymesia/`. Background extraction sends relevant conversation material to the model used by your agent, after masking detected credentials. This is not fully offline processing.
- Background writing uses your agent's own model access and quota. Automatic selection considers available acceptance results, speed, token usage and price. Extra usage varies; there is no guaranteed overhead percentage.
- Personal memories are shared across projects; project memories belong to their project.

Source repositories: [GitHub](https://github.com/ymdfker/Hyperthymesia) · [AtomGit](https://atomgit.com/ynndfker/Hyperthymesia). The installation commands below download published **GitHub Release** assets. Synchronizing source code to AtomGit does not create an AtomGit binary release.

### 1. Install and connect your agent

Choose the identifier for your agent:

| Agent | Identifier |
|---|---|
| Claude Code | `claude` |
| Codex | `codex` |
| WorkBuddy desktop | `workbuddy` |
| Qoder | `qoder` |
| DeepSeek Harness | `dsh` |

**macOS / Linux:** open Terminal and run the following. Replace `claude` with your agent's identifier from the table.

```bash
AGENT=claude
curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- "$AGENT"
```

**Windows:** open PowerShell and run the following. Replace `claude` with your agent's identifier.

```powershell
$env:HY_AGENTS="claude"
irm https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.ps1 | iex
```

No Python installation is required for the packaged executable. Wait for the installer to report completion. Repeat for each agent you use.

**Current release: v0.2.5.** It includes the WorkBuddy desktop configuration fix, internal-task isolation, updated background model selection and a shared assistant-suggestion policy. The commands above install the latest GitHub Release. Users of v0.2.4 should rerun installation and restart WorkBuddy.

### 2. Complete your agent's setup

- **Claude Code:** fully quit all Claude Code windows or terminal sessions, then reopen it.
- **Codex:** fully quit and reopen Codex. Enter `/hooks` and approve/trust the Hyperthymesia hooks. Without approval, the hooks will not run.
- **WorkBuddy:** fully quit and reopen the app. In its MCP settings, ensure `hyperthymesia` is enabled and connected. With the source fix, desktop settings use `~/.workbuddy/settings.json` and `~/.workbuddy/mcp.json`; existing files are backed up and CodeBuddy CLI settings are preserved. Use `hyperthymesia install codebuddy` for the separate CLI.
- **Qoder:** the installer sets up the official `qodercli` used for background writing. Run `qodercli login`, complete browser authorization, then fully restart Qoder. If the installer requires npm, install Node.js LTS from [nodejs.org](https://nodejs.org/) and rerun installation.
- **DeepSeek Harness:** use the DeepSeek API key already configured in dsh. If needed, run `dsh web`, open Settings → Models, configure DeepSeek and save. Obtain a key from [DeepSeek Platform](https://platform.deepseek.com/). Restart dsh by stopping `dsh web` with Ctrl+C and launching it again. Hyperthymesia does not require you to copy the key into its own configuration.

### 3. Check the connection and use it normally

In a new Terminal or PowerShell window, run the command for your agent:

```bash
hyperthymesia doctor --agent claude
hyperthymesia doctor --agent codex
hyperthymesia doctor --agent workbuddy
hyperthymesia doctor --agent qoder
hyperthymesia doctor --agent dsh
```

Run only the relevant line. The writer provider should match your agent; WorkBuddy reports `codebuddy`, its underlying runtime. `doctor` checks configuration, not the complete capture/write/recall chain. Also check the MCP connection and actual hook activity. See the [compatibility notes](docs/desktop-compat.md), currently maintained in Chinese.

Chat and work normally. Hooks record completed turns and code changes; background writing runs when enough material has accumulated or a supported lifecycle event triggers it. Memory is not necessarily saved immediately after each reply. To inspect what a project would receive:

```bash
hyperthymesia context /path/to/project
```

### WorkBuddy desktop limitations

On the tested WorkBuddy 5.3.14, normal desktop quit did not reliably deliver `SessionEnd`, even after the runtime was ready and `SessionStart` had fired. Material below the batch threshold may remain pending until the next session-start event triggers background writing. Opening the home screen alone does not guarantee that event; entering an existing chat was verified. A question asked before writing finishes may miss the pending information. Already stored memories remain readable. No fixed waiting time is guaranteed.

The tested version also ignores the `disableAllHooks` setting. This is recorded as a host limitation; Hyperthymesia does not override it with another switch. To disconnect, remove Hyperthymesia's integration using the uninstall command and restart the host.

An earlier desktop run exposed recursive recording of background tasks. Source code now marks internal calls and skips their hooks. A subsequent isolated desktop test saved and recalled all seven target facts correctly, but had model-selection and latency deviations; this is a partial acceptance result, not full desktop certification. The subsequent model-selection and suggestion-policy changes have local checks, not a new paid end-to-end acceptance.

### Optional operations

**Import earlier chats:**

```bash
hyperthymesia import --list
hyperthymesia import --agent claude --session SESSION_ID
```

Replace `claude` and `SESSION_ID` as needed. `--all --days 7` imports chats from the last seven days. Historical code changes cannot be reconstructed by this import.

**Try a single project:**

```bash
hyperthymesia install claude --project /path/to/project
```

Project installation supports `claude`, `codex`, `codebuddy`, `workbuddy` and `qoder`. dsh integration is profile-based and does not provide project-level installation isolation.

**Use a separate OpenAI-compatible API for background writing:** create `~/.hyperthymesia/config.toml` only if you want to override your agent's normal model access:

```toml
[writer]
provider = "openai"
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
```

Put the actual key in the named environment variable, not in this file.

**Upgrade:** rerun the installation command for your agent. This replaces the executable and refreshes integration while retaining memories. It installs the latest published release, not unreleased source changes.

**Uninstall:** run `hyperthymesia uninstall claude`, substituting your agent's identifier. It removes Hyperthymesia's integration entries and preserves other settings. Memories remain on disk; deleting `~/.hyperthymesia/` permanently removes them.

### Troubleshooting

- **Command not found:** reopen Terminal/PowerShell. If necessary, use `~/.local/bin/hyperthymesia` on macOS/Linux or `%USERPROFILE%\.hyperthymesia\bin\hyperthymesia.exe` on Windows (the latter is a Command Prompt path; in PowerShell use `$env:USERPROFILE`).
- **macOS blocks the executable:** open System Settings → Privacy & Security and choose Open Anyway if offered.
- **New information is missing:** inspect the capture/write logs and allow background writing to finish; a connected MCP server alone does not prove that hooks captured or saved the conversation.
- **IDE, desktop and Windows support:** CLI acceptance does not establish equivalent behavior in every GUI. Several GUI variants, a real Windows installation/hooks workflow and a full week of everyday use remain unverified. See [compatibility notes](docs/desktop-compat.md) for scope and known issues.

### Command reference

| Command | Purpose |
|---|---|
| `install <agent> [--project PATH]` | Connect an agent; existing configuration is backed up |
| `uninstall <agent> [--project PATH]` | Remove integration while preserving unrelated settings |
| `doctor [--agent AGENT]` | Inspect the writer configuration and model |
| `context [PATH]` | Show the memory context for a directory |
| `write` | Manually process pending completed turns; normally automatic |
| `import --list` / `import --agent AGENT --session ID` | Import earlier chats |

For development, the implementation uses Python's standard library. Run `python3 -m unittest discover -s tests -v`. GitHub Actions tests and packages pushes to `main`; `v*` tags additionally publish GitHub Releases.
