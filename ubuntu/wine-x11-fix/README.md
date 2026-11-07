# Wine 11.20 企业微信修订

当前源码对应企业微信 5.0.13.6005-5 测试版。
[组件清单](../release.json)、[测试结果](../validation.json)及[实现 review](CODE-REVIEW.md)分别记录构建、运行与验证状态。

## 实现

主体、标题和阴影共用原生外框，附属层按 owner 的同一坐标快照提交。
几何确认、像素上传与 XSync 完成计数形成同一绘制事务，跨进程内容通过 XDamage 刷新。
窗口层级、焦点协议、形状裁剪和显示原点分别使用原生窗口状态处理。

适配器声明 `WINE_X11_FRAME_ATTACHED_CLASSES='PerryShadowWnd;TitleBarWindow'`，
由 `WINE_X11_FRAME_DECORATION_CLASSES=PerryShadowWnd` 指定主体后方的装饰层。
成员卡和独立弹窗保留各自的坐标及层级。

其余修订包括输入法候选锚点、文件选择与文件管理器接口、剪贴板文件 URI、字体、
GDI+ 采样、设备关系查询和 UDisks 通知。-5 还调整了升级启动与最大化窗口的全屏判定。
后续源码修复了仅 Wine 后台驻留时的升级切换，并调整窗口状态与布局提交的时序。
具体因果和保留问题见 [CODE-REVIEW.md](CODE-REVIEW.md)。

## 构建

原始归档为 [Wine 11.20](https://github.com/wine-mirror/wine/archive/refs/tags/wine-11.20.tar.gz)，
SHA256：`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
打包脚本将原始归档、当次累计补丁、构建脚本、适配器源码和 LGPL 放入 DEB 的 `/usr/share/doc/com.qq.wecom.spark/`。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v /absolute/build-area:/work \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/new-output
```

Unix 与 PE 组件分别构建，PE 同时提供 x86/x64。
GDI ABI 保持 112，`win32u.so`、X11、打印和 Wayland 驱动成套部署。
IMM32 公开调用约定未变；修复后的蓝牙 Unix 模块 `winebth.so` 与其余组件按清单装配。
构建路径和工具链会影响二进制哈希；打包步骤见[构建说明](../../UBUNTU.md)。

## 回归

[统一测试入口](tests/README.md)覆盖窗口、绘制、输入法、字体、文件接口、剪贴板、设备和升级场景。
各组也可独立运行，测试创建私有显示会话和空白 prefix，并记录所用组件指纹。

```sh
python3 ubuntu/wine-x11-fix/tests/run-suite.py \
  --files /absolute/package-files --source /absolute/patched-wine-source \
  --previous-files /absolute/previous-package-files --output /absolute/new-qa
```

KWin、niri 与真实客户端的操作清单单列在测试说明中。
退出码和报告中的失败均保留，当前遗留问题汇总在实现 review 和验证记录中。
