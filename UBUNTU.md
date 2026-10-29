# Ubuntu 使用、复用与重建

当前版本为企业微信 5.0.13.6005 / 私有 Wine 11.20（2026-10-30，DEB 5.0.13.6005-1）。
验收环境为 Ubuntu 26.04.1 amd64、GNOME 50.1 Wayland/XWayland、双屏 200%、IBus/Rime。
其他发行版、桌面和缩放比例需要另行验证。

程序与未登录模板位于 `/opt/apps/com.qq.wecom.spark/files`。
用户 prefix 位于 `${XDG_DATA_HOME:-$HOME/.local/share}/wecom/prefix`，日志在相邻的 `logs` 目录。
首次启动按当前 Linux 用户重定位模板，升级沿用账号目录并使用安装包内的启动器、助手。
企微的配置修改只作用于该 prefix，不改系统 Wine 或桌面全局设置。

## 修复与边界

邮件跨进程正文通过原生像素变化通知更新共享框架；主进程不必再次调用 GDI 才能看到新内容。
合成内容的待处理状态独立于通知队列，应用重入消息循环时不会丢掉更新，状态解锁后重新排队。
绘图提交保持应用完成信号和 XSync 协议，移除了持有窗口锁时等待合成器私有属性的轮询。
人物卡片与头像预览使用稳定的原生 owner 关系，同 owner 的共享框架也能按 Win32 请求换序。
普通 `WS_EX_TRANSPARENT` 不再被直接当作整窗鼠标穿透；分层透明窗口继续允许穿透。

顶栏、主体和阴影在一个原生框架中提交，缓冲区按窗口尺寸复用。
原生模式不再为顶栏添加 `WS_SYSMENU` 或清除 `WS_EX_NOACTIVATE`，也不重放普通菜单点击。
主窗口阴影保持被动输入角色，这是企微适配。实现说明见[当前实现](ubuntu/wine-x11-fix/CODE-REVIEW.md)。

CEF 修订仅接受固定 SHA256 的原厂 x86 DLL，回补 V8 保护模式和 Chromium 光标坐标处理。
原 CEF 签名因此失效；`WXWork.exe` 没有修改。不能将此补丁直接套用到其他企微版本。
邮件进程在该 prefix 中设置 IFEO `dpiAwareness=1`，与主进程的 DPI 模式保持一致。

托盘菜单定位及 XWayland 截图黑屏仍未修复。图片准备、网络取数与桌面开窗动画仍有耗时。
附件收发、审批、音视频、已读人数等功能未全面验收，不能据此承诺企业微信全部功能可用。

## 构建 Wine 与助手

Wine 原始归档 SHA256：
`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
原始源码、完整净补丁、SDK Dockerfile、构建脚本及 LGPL 随包提供。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v /absolute/build-area:/work \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/new-output
bash ubuntu/build-helpers.sh /absolute/helper-output
```

运行时需配套部署核心、图形、输入法和设备管理组件，完整清单及构建命令见
`ubuntu/wine-x11-fix/README.md`。
当前二进制来自已记录的 SDK 构建，干净源码重建另有验证；不同编译路径和工具链会改变二进制哈希。

## 重建未登录安装包

公开 R3 DEB 是已校验的模板来源，无须维护者的历史构建缓存或已登录 prefix。
`package.py` 校验来源、运行时和助手哈希，剥离 Wine PE 调试数据并核对其运行时 section 不变。
厂商 DLL 不执行 strip。重复文件在包内去重，首次创建用户目录时解除硬链接以保持文件独立。

```sh
python3 ubuntu/package.py \
  --base-package /absolute/com.qq.wecom.spark_5.0.12.6018-3.preview20261025_amd64.deb \
  --runtime /absolute/verified-wine-runtime \
  --helpers /absolute/verified-helpers \
  --wine-source /absolute/wine-11.20.tar.gz \
  --installer /absolute/WeCom_5.0.13.6005.exe \
  --stage /absolute/new-stage \
  --output /absolute/com.qq.wecom.spark_5.0.13.6005_amd64.deb
```

自行构建后更新 `release.json` 中的组件指纹，再运行打包。
公开基包必须匹配元数据中的 SHA256，不能换成任意已登录的账号目录。
基础安装器、运行库与字体来源保存在 `materials/`，仍须遵循原许可。
这套流程可重建 Wine 与适配包，不等于从零重现所有第三方安装器的安装过程。

## 独立回归与 DPI

`ubuntu/wine-x11-fix/tests/frame-composition/` 包含跨进程绘制、输入穿透、owner 和共享框架换序用例。
它们在私有 GNOME/XWayland 会话中运行，使用合成窗口和账号无关的测试 prefix。
真实客户端的场景与通过范围单列于 `validation.json`，不会以模型测试替代实际客户端验收。

模板默认 192 DPI（200%）。调整其他缩放时先退出企微，再只修改专属 prefix：

```sh
WINEPREFIX="$HOME/.local/share/wecom/prefix" \
  /opt/apps/com.qq.wecom.spark/files/wine/bin/wine winecfg
```

新源码、组件或缩放组合须重新验收，不能沿用旧版本的通过结论。
