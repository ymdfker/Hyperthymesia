#!/bin/sh
# Hyperthymesia 一键安装（macOS / Linux）：
#   curl -fsSL https://github.com/ymdfker/Hyperthymesia/releases/latest/download/install.sh | sh -s -- claude
# 末尾的 agent 名（claude / codex / workbuddy / qoder / dsh，可写多个）可省略；写了就顺带接入这些 agent。
set -e
REPO=ymdfker/Hyperthymesia
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) A=hyperthymesia-macos-arm64 ;;
  Darwin-x86_64) A=hyperthymesia-macos-x64 ;;
  Linux-x86_64) A=hyperthymesia-linux-x64 ;;
  *) echo "暂不支持此系统：$(uname -s) $(uname -m)"; exit 1 ;;
esac
DIR="$HOME/.local/bin"; BIN="$DIR/hyperthymesia"
mkdir -p "$DIR"
echo "下载 $A ……"
curl -fL --progress-bar "https://github.com/$REPO/releases/latest/download/$A" -o "$BIN.tmp"
chmod +x "$BIN.tmp" && mv "$BIN.tmp" "$BIN"
[ "$(uname -s)" = Darwin ] && xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true   # 去掉“无法验证开发者”拦截
echo "已安装到 $BIN"
for agent in "$@"; do "$BIN" install "$agent"; done
# 自动把 ~/.local/bin 加进 PATH：按登录 shell 追加到对应启动文件，已有则不重复
case ":$PATH:" in *":$DIR:"*) ;; *)
  LINE='export PATH="$HOME/.local/bin:$PATH"   # hyperthymesia'
  case "$(basename "${SHELL:-sh}")" in
    zsh) RCS="$HOME/.zshrc" ;;
    bash) RCS="$HOME/.bashrc"; [ "$(uname -s)" = Darwin ] && RCS="$RCS $HOME/.bash_profile" ;;
    *) RCS="$HOME/.profile" ;;
  esac
  for rc in $RCS; do
    grep -qs '.local/bin' "$rc" || { printf '\n%s\n' "$LINE" >> "$rc"; echo "已把 $DIR 加入 PATH（写入 $rc），新开的终端即可直接用 hyperthymesia 命令"; }
  done ;;
esac
[ $# -gt 0 ] && echo "完成：请完全退出并重新打开你的 agent。" || echo "下一步：$BIN install claude（换成你用的 agent），然后重启 agent。"
