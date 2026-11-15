# 邮件正文输入回归

邮件正文的实际焦点是跨进程 `CefBrowserWindow` 下的 `Chrome_WidgetWin_0`。
旧桥接只接受 `Chrome_WidgetWin_1`，因此跳过正文的 XIM commit。
修复只补全这个类名，保留进程、父窗口、XIM 客户端和焦点检查。

`mail-body.c` 创建真实的跨进程 Win32 子窗口，用 Unicode `WM_CHAR` 接收输入，
并模拟 CEF 不处理 IMM commit 的行为。主题栏使用标准 Unicode Edit。
`run.py` 通过真实 Fcitx5 拼音和 XIM 提交“你好”，随后检查英文输入与主题栏。
它同时检查原有 `_1` 路径，以及同进程、其他父类和 `_2` 不被桥接的边界。

在独立 KWin/Xwayland 会话中运行，使用单独的 D-Bus、Fcitx 配置和 Wine prefix。
不要将日常桌面的环境文件传给脚本。`--output` 必须尚不存在，且与私有 runtime
位于同一个测试目录。需要 Python 3、Fcitx5 拼音、libX11、libXtst 和 GLib 命令行工具。

```sh
x86_64-w64-mingw32-gcc -std=c11 -Wall -Wextra -Werror -O2 \
  mail-body.c -o /qa/WeMail.exe -luser32 -lgdi32
python3 run.py --session-env /qa/session-env.json --runtime /package/wine \
  --fixture /qa/WeMail.exe --baseline /qa/baseline.so \
  --candidate /qa/candidate.so --output /qa/regression
```

基线和候选库分别由修改前后的 `scripts/ime-bridge.c` 使用
`ubuntu/build-helpers.sh` 中的编译参数构建。结果写入 `result.json`。
该测试验证 XIM 与真实 Wine API 的集成，企业微信及 WeTypeX 的完整验收仍使用实际客户端。
