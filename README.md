# Hyperthymesia

给 AI agent 用的长期记忆。装上之后，你在 Claude Code、Codex、WorkBuddy、Qoder 里说过的事实、做过的决定、
代码里定下的约定，下一次新开会话时 agent 依然记得——不用你再交代一遍。

- **跨会话记得**：新会话一开始，agent 就能看到之前记下的事实和最新状态（改过的值只保留最新的）。
- **编程场景记得代码里的决定**：agent 自己在代码里定的配置值、路径、命名约定，即使回复里没说，也会被记下。
- **个人与项目分开**：个人的事（家人、偏好、习惯）在所有项目里都可用；每个项目的约定只在这个项目里可见，项目之间互不混淆。
- **花费很少**：记忆由后台自动整理，用你当前 agent 最便宜且够用的模型、用它自己的额度；实测约占 agent 本身花费的 1%–2%。
- **数据在本机**：记忆存在你电脑上的 `~/.hyperthymesia/`，不上传任何服务器；密码、密钥等凭据在整理前会被遮盖，不会进入记忆。

## 支持的 agent

| agent | 安装命令 | 额外需要你做的 |
|---|---|---|
| Claude Code | `hyperthymesia install claude` | 无 |
| WorkBuddy | `hyperthymesia install workbuddy` | 无 |
| Codex | `hyperthymesia install codex` | 在 Codex 里输入 `/hooks`，批准 hyperthymesia 的钩子 |
| Qoder | `hyperthymesia install qoder` | 按提示安装 qodercli，并执行一次 `qodercli login` |

装完后**重启一次 agent**，让它读到新配置。

## 快速开始

1. **下载**：到 [Actions 构建记录](https://github.com/ymdfker/Hyperthymesia/actions) 最新一次成功构建的 Artifacts 里，
   下载对应系统的单个可执行文件（macOS、Windows、Linux 各一个），放到任意目录，例如 `~/bin/hyperthymesia`
   （Windows 为 `hyperthymesia.exe`）。不需要安装 Python 或其他运行环境。
   - macOS 首次运行若提示“无法验证开发者”：在“系统设置 → 隐私与安全性”中点“仍要打开”。
   - Windows 若弹出 SmartScreen：点“更多信息 → 仍要运行”。
2. **安装到你的 agent**：

   ```bash
   hyperthymesia install claude
   ```

   把 `claude` 换成 `workbuddy`、`codex` 或 `qoder`。只想在某个项目里试用：加 `--project 项目目录`，只改这个项目自己的配置。
3. **重启 agent**，正常使用即可。记忆会在后台自动整理，你什么都不用管。
4. **检查是否就绪**：

   ```bash
   hyperthymesia doctor
   ```

   显示当前用哪个 agent 的哪个模型整理记忆，以及命令行是否可用（不显示任何密钥）。

## 它是怎么工作的

```
你 ⇄ agent（Claude Code / Codex / WorkBuddy / Qoder）
        ↑ 每轮开始：注入相关记忆           ↑ 需要时：通过 MCP 工具读取更多记忆
        │                                  │
   hyperthymesia 钩子                 hyperthymesia serve（只读）
        │ 每轮结束：记下对话和代码改动
        ▼
   积压够多 / 即将压缩 / 会话结束 → 后台整理（用该 agent 最便宜的模型）→ ~/.hyperthymesia/
```

- **读**：库小时，每轮把记忆直接注入给 agent；库大时只注入目录，agent 按需读取。
- **写**：只整理已完成的对话轮次——你的原话、agent 的最终回复、本轮代码改动；由程序校验后写入，旧值被新值取代时自动失效。
- **整理用的模型**：自动列出你当前 agent 能用的模型，挑最便宜且通过能力试探的一个，用这个 agent 自己的额度，
  不会动用别家的服务；每周重新确认一次。

## 用 API key 的用户

如果你给 agent 配置的是自己的 API key（比如在 WorkBuddy、Claude Code、Codex 里填了 DeepSeek 或 OpenAI 的 key），
**不需要再做任何配置**：后台整理借用该 agent 的命令行，它会用你已经配置好的 key 和模型。

只有在你想让记忆整理走另一个 API 时，才需要在 `~/.hyperthymesia/config.toml` 写：

```toml
[writer]
provider = "openai"                      # 任意 OpenAI 兼容接口
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"         # 只写环境变量名：运行时从环境读取，不保存、不复制 key
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `hyperthymesia install <agent> [--project 目录]` | 接入某个 agent（只增加本工具的配置，原配置先备份） |
| `hyperthymesia uninstall <agent> [--project 目录]` | 移除本工具的配置，还原原样 |
| `hyperthymesia doctor` | 自检：整理记忆用的是哪个模型、是否可用 |
| `hyperthymesia context [目录]` | 查看在该目录下会注入给 agent 的记忆 |
| `hyperthymesia write` | 立即整理积压的对话（平时由后台自动完成） |

## 数据与隐私

- 所有记忆保存在本机 `~/.hyperthymesia/`（Windows：`%USERPROFILE%\.hyperthymesia\`）：`personal.db` 为个人库，
  `projects/` 下每个项目一个库。删除这个目录即清空全部记忆。
- 记录代码改动时不读取 `.env`、私钥、证书、`.ssh` 等凭据文件；其余文本中的密码、令牌、带密码的连接串在送去整理前会被遮盖。
- 不修改你的代码仓库：代码改动通过独立的影子仓库记录，你的 git 历史、暂存区不受影响。

## 开发

- 只用 Python 标准库；运行测试：`python3 -m unittest discover -s tests -v`
- 每次推送到 main，GitHub Actions 在 macOS、Windows、Linux 上运行测试、用 PyInstaller 打出单个可执行文件，并对产物做冒烟测试。
- 本地打包：`python -m pip install pyinstaller` 后执行 `.github/workflows/build.yml` 里的打包命令。PyInstaller 只在构建时需要。
