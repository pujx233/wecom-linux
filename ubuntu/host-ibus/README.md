# 本机 IBus 取消竞态

Ubuntu 本机 `ibus 1.5.34~rc2-1` 在 2026-11-15 06:50:56 崩溃，栈顶为
`g_task_return_error()`，调用者对应 `create_engine_ready_cb()`。
这次崩溃发生在 R7 企微重启和桌面测试之前。

`bus_engine_proxy_new()` 同时等待引擎 factory、超时和取消。
原 `cancelled_cb()` 排入 idle 回调时，仍保留 factory 通知与超时；
另一条完成路径可先释放任务，随后回调再次访问已释放对象。
补丁在排入取消 idle 前撤销另外两个来源，保留 idle 中断开 cancellable 的规则，避免死锁。

补丁来自已合并的 [IBus PR #2958](https://github.com/ibus/ibus/pull/2958)，
提交 `14ec1665333d74cc696453e4ba12bc10840dabd1`；仅选择该版本使用的 Autotools 文件。
同类现场见 [上游 issue #2957](https://github.com/ibus/ibus/issues/2957)。

## 验证和本机安装

源码使用 Ubuntu 官方 `1.5.34~rc2-1` 源码包，并保留其发行版补丁。
两个上游测试在修复前分别于 `create_engine_ready_cb()` 和 `cancelled_idle_cb()`
触发 ASan heap-use-after-free；应用修复后，两项均通过 ASan 和 LeakSanitizer。
测试对象独立编译，未将 ASan 引入日常守护进程。

本机只重新编译 `bus/ibus-daemon`，链接已安装的系统 `libibus-1.0.so.5`；
保留发行版守护进程使用的 `-DEMOJI_DICT`。
禁用 GTK、文档和词典的构建开关只用于跳过无关目标，未替换系统输入模块、词典或配置组件。
普通编译命令为：

```sh
make -j6 -C bus ibus-daemon \
  'ibus_daemon_CFLAGS=$(AM_CFLAGS) -DEMOJI_DICT' \
  libibus=/usr/lib/x86_64-linux-gnu/libibus-1.0.so.5
```

日常进程使用 `$HOME/.local/lib/wecom-ibus-cancel/ibus-daemon`。
`ibus-daemon-guard.sh` 检查发行版版本、原守护进程、系统 libibus 和修补后二进制的 SHA256；
不匹配时执行系统守护进程。用户级 IBus service 覆盖只替换可执行文件，保留原参数和重启规则。
系统 `/usr/bin/ibus-daemon` 未修改，此修复不包含在企微 DEB 中。

结构化证据位于 `/home/sai/work/.wecom-build/r7/ibus-*-results.json`、
`ibus-local-deployment.json` 和相关构建日志。
真实企微 PID 690911 未因 IBus 替换而重启，之后中文候选和“测试”上屏通过，测试文字已清除。

## XIM 生命周期

GNOME Wayland 的发行版脚本只在 Xwayland 启动时执行一次 `ibus-x11`。
IBus 重启会使前端退出，原生输入模块可以恢复，Wine 的 XIM 却没有服务器。

`org.freedesktop.IBus.X11.service` 管理前端；IBus daemon 通过
`60-xim-lifecycle.conf` 拉起它，停止和重启通过 `PartOf` 与 `After` 保持先后关系。
前端不使用会主动结束 daemon 的 `--kill-daemon`，单独退出由 systemd 重建。
Wayland 与 DISPLAY 条件使 X11 会话继续使用发行版 daemon 的 `--xim` 路径。
GNOME 会话结束时，前端随 `gnome-session-initialized.target` 一起停止。

`10-ibus-x11` 替换发行版的一次性启动入口。在本次 Xwayland 环境中导入 DISPLAY、
XAUTHORITY 后启动同一用户服务，避免两条入口分别创建前端。
未启用此用户服务、非 GNOME 或非 Wayland 会话继续走发行版原入口。
这项修复不注入企微，不轮询 XIM owner，也不通过重启 Wine 恢复输入。

安装前保存 `/etc/xdg/Xwayland-session.d/10-ibus-x11`，然后执行：

```sh
mkdir -p "$HOME/.config/systemd/user/org.freedesktop.IBus.session.GNOME.service.d"
install -m 0644 org.freedesktop.IBus.X11.service "$HOME/.config/systemd/user/"
install -m 0644 60-xim-lifecycle.conf \
  "$HOME/.config/systemd/user/org.freedesktop.IBus.session.GNOME.service.d/"
sudo install -m 0755 10-ibus-x11 /etc/xdg/Xwayland-session.d/10-ibus-x11
systemctl --user daemon-reload
```

安装后重新登录桌面，交接发行版原先直接启动的前端。
本机已经在当前会话单独完成前端交接，两次 daemon 重启均自动恢复前端。
系统钩子已在管理员认证后安装，并核对与仓库脚本逐字节一致；
安装后调用该钩子仍只有一个前端。下次完整桌面登录尚未单独验收。

撤销前端管理时，恢复安装前的系统脚本，删除上述用户 service 与
`60-xim-lifecycle.conf`，执行 `systemctl --user daemon-reload`，再重新登录桌面。
撤销取消竞态修补时，另删除 `50-wecom-cancel-fix.conf` 并重新加载用户服务。
