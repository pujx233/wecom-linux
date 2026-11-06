# Wine 11.20 企业微信修订

企业微信 5.0.13.6005 / Ubuntu 26.04 amd64，2026-11-02。
当前源码与本地使用的最终组件一致，完整清单见 [release.json](../release.json)。
实现说明见 [CODE-REVIEW.md](CODE-REVIEW.md)，测试摘要见 [validation.json](../validation.json)。

## 当前实现

- 主体、标题和阴影共用原生外框；附属层按 owner 的同一坐标快照提交，局部更新不回写全局位置。
- 合成等待窗口配置确认，最终像素复制完成后才发布 XSync 完成计数，跨进程更新通过 XDamage 推进。
- 分组层级同步保留已获得的前台位置，修复前后台切换、最小化恢复和成员卡顺序。
- 显示链接重绑定及原点换算修复拔屏后的裁切；保留双屏最大化和还原修订。
- 输入法候选框使用当前输入对应的 caret 底边，保留显式候选点和排除区域语义。
- PnP 按需查询关系、合并重复通知并清理旧缓存；Mountmgr 只响应 UDisks2。
- GDI+ 减少重复采样运算；OpenGL、foreign DC 使用实际 visual。

`WINE_X11_FRAME_ATTACHED_CLASSES='PerryShadowWnd;TitleBarWindow'` 声明随主体移动的附属层。
成员卡和独立弹窗不声明该角色，保持绝对定位。
`WINE_X11_FRAME_DECORATION_CLASSES=PerryShadowWnd` 决定正文后方的绘制顺序。

当前使用 X11/XWayland。GDI ABI 为 112，`win32u.so`、`winex11.so`、`wineps.so`、
`winewayland.so` 及两份 IMM32 必须配套；设备管理、Wineboot 和其余组件按清单装配。

## 构建

原始源码：[Wine 11.20](https://github.com/wine-mirror/wine/archive/refs/tags/wine-11.20.tar.gz)。
SHA256：`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
DEB 的 `/usr/share/doc/com.qq.wecom.spark/` 提供原始归档、净补丁、构建脚本、适配器源码及 LGPL。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v /absolute/build-area:/work \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/new-output
```

Unix 组件使用 `--enable-win64 --without-mingw --with-wayland`。
PE 组件单独使用 MinGW 构建，GDI+、IMM32 和设备管理组件同时提供 x86/x64。
不同构建路径和工具链会改变二进制哈希，打包前更新完整组件清单。

## 测试

- [frame-composition](tests/frame-composition/README.md)：附属层坐标、跨进程显示、输入、层级及显示变化。
- [draw-completion](tests/draw-completion/README.md)：绘图完成信号与 CS_OWNDC。
- [ime-position](tests/ime-position/README.md)：DPI、composition、候选锚点与焦点切换。
- [pnp-relations](tests/pnp-relations/README.md)：设备关系、通知和旧缓存迁移。
- `tests/package-upgrade.py`：独立环境中的首次启动、繁忙目录处理、升级和再次启动。
- `tests/run-native-file-dialogs.py`：32/64 位 Portal 结果、取消、回调、服务退出和文件管理器协议。

原生文件接口用例必须使用独立显示会话及无账号 prefix，在其父目录创建 `.wecom-native-file-qa` 标记。
脚本自动创建私有 D-Bus 会话并启动模拟服务，不替换当前桌面的 Portal：

```sh
python3 tests/run-native-file-dialogs.py --runtime /absolute/wine \
  --prefix /absolute/private-qa/prefix --output /absolute/private-qa/results
```

需要 Python GI、dbus-run-session、双架构 MinGW 编译器及已初始化的测试 prefix。
容器没有编译器时，可用 `--fixtures /absolute/probes` 指定已编译的 `probe32.exe`、`probe64.exe`。
模拟协议通过后，还应在真实桌面后端验证选择、取消、中文路径和 Linux 文件管理器，不能只验模拟服务。

隔离用例使用私有显示会话及无账号 prefix。当前四项附属坐标回归、现场快速拖动和最大化还原通过。
低频卡片遮挡、完整混合 DPI 和 CFS_RECT 路径尚未全部验证。
托盘菜单定位、XWayland 截图黑屏、Wine 蓝牙名称字符串泄漏仍未解决；邮件和头像首次加载仍有耗时。
