# Hyperthymesia

给 AI agent 用的长期记忆。接入后，你在 Claude Code、Codex、WorkBuddy、Qoder、DeepSeek Harness 里说过的事实、做过的决定、
代码里定下的约定，新开会话时 agent 依然记得，不用再交代一遍。

- 记忆存在你电脑上（`~/.hyperthymesia/`），不上传；密码、密钥会先遮盖。
- 后台自动整理，用你 agent 自己最便宜的模型和额度，约占 agent 花费的 1%–2%。
- 个人的事所有项目通用；每个项目的约定只在该项目里可见。

## 接入步骤

找到你用的 agent，只按那一节一步步做（约 3 分钟）。用多个 agent 就每一节各做一遍。

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

“写入提供方”后面显示 `claude` 就说明接入成功。之后正常使用 Claude Code 即可，什么都不用管。

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

“写入提供方”后面显示 `codex` 就说明接入成功。之后正常使用 Codex 即可，什么都不用管。

### WorkBuddy

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

“写入提供方”后面显示 `codebuddy`（WorkBuddy 内置的就是 CodeBuddy） 就说明接入成功。之后正常使用 WorkBuddy 即可，什么都不用管。

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

“写入提供方”后面显示 `qoder` 就说明接入成功。之后正常使用 Qoder 即可，什么都不用管。

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

“写入提供方”后面显示 `dsh` 就说明接入成功。之后正常使用 DeepSeek Harness（dsh） 即可，什么都不用管。

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

**只在某个项目里试用**：`hyperthymesia install 你的agent --project 项目目录`（agent 名：claude、codex、workbuddy、qoder、dsh）。

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

**卸载**：`hyperthymesia uninstall 你的agent`（还原原配置）。删除 `~/.hyperthymesia/` 即清空全部记忆。

## 常用命令

| 命令 | 作用 |
|---|---|
| `install <agent> [--project 目录]` | 接入 agent（原配置先备份） |
| `uninstall <agent> [--project 目录]` | 移除接入，还原原配置 |
| `doctor [--agent X]` | 自检：该 agent 用哪个模型整理、是否可用 |
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
