# 使用与构建

当前测试版为企业微信 5.0.13.6005-5，内置私有 Wine 11.20。
安装方式见 [README](README.md)，组件指纹与测试结果分别保存在
[release.json](ubuntu/release.json) 和 [validation.json](ubuntu/validation.json)。

## 用户目录

程序和未登录模板安装在 `/opt/apps/com.qq.wecom.spark/files`。
首次启动为当前 Linux 用户创建 `${XDG_DATA_HOME:-$HOME/.local/share}/wecom/prefix`，日志保存在相邻的 `logs` 目录。
升级保留这个目录中的账号和聊天数据，空闲时更新应用、字体及配套组件。
-5 支持在运行期间再次启动唤回现有客户端，并区分应用客户端与 Wine 后台服务：
应用退出后，下次启动会先结束这个 prefix 的残留后台，再完成更新。
升级切换的实现与测试见[review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md#升级切换)。

配置只作用于企业微信自己的 prefix。桌面 DPI 优先取自 XSettings 和 X resources，再读取桌面的显示配置。
用户手工修改的 DPI 会保留。退出客户端后，可以指定 DPI 或恢复自动配置：

```sh
WECOM_DPI=120 /opt/apps/com.qq.wecom.spark/files/start.sh
WECOM_DPI=auto /opt/apps/com.qq.wecom.spark/files/start.sh
```

初始化、升级和启动统一使用中文 locale，避免 Wine 重建代码页时覆盖字体回退表。

## 文件窗口

上传文件使用桌面的 FileChooser Portal，打开目录和定位文件使用 Linux 默认文件管理器。
支持中文路径、多选、保存、取消及 COM 确认回调。
带 Win32 自定义控件的窗口，以及旧式文件对话框接口，继续使用 Wine 界面；当前图片菜单的“另存为”属于后者。

桌面需提供 Portal 文件选择后端和目录默认应用。要使用 Wine 界面，可分别设置
`WINE_NATIVE_FILE_DIALOGS=0` 或 `WINE_NATIVE_FILE_MANAGER=0`。

niri 额外标题栏的中文方块来自 xwayland-satellite 的字体回退，修复位于
[独立补丁](ubuntu/xwayland-satellite-fonts/README.md)，由使用该组件的桌面单独部署。

## 依赖

核心 glibc 下限由包内 ELF 符号计算，当前为 **2.38**。
Unix 模块均为 amd64，32 位 Windows 程序通过 WoW64 运行，无需 i386 系统库或系统 Wine。
`7zz` 用于构建时解压厂商安装器，首次启动直接复制模板。

| 分类 | 用途 |
| --- | --- |
| Depends | 启动脚本、Python、X11、字体、DBus、GnuTLS、CA 证书，以及 PulseAudio 或 ALSA |
| Recommends | XWayland、桌面 Python 绑定、OpenGL/Vulkan、音视频、打印和设备支持 |
| Suggests | 扫描仪、相机导入、智能卡、OpenCL、SMB、ODBC 等扩展 |

同 ABI 的 t64 与非 t64 包名使用替代依赖。Wine 多媒体后端按实际链接声明：
`winegstreamer.so` 使用 GLib 2.80、GStreamer 1.14 和 base 库 1.18；
`winedmo.so` 使用 FFmpeg 8 的 `libavformat.so.62`、`libavcodec.so.62` 和 `libavutil.so.60`。
音视频组件仍保留厂商自带的 Windows 编解码库，实际功能按桌面环境测试。

## 构建 Wine

Wine 原始归档 SHA256 为
`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
原始源码、累计补丁、SDK Dockerfile、构建脚本及 LGPL 随包提供。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v /absolute/build-area:/work \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/new-output
bash ubuntu/build-helpers.sh /absolute/helper-output
```

当前源码保留 GDI ABI 112，核心、X11、Wayland 和打印驱动按组件清单配套构建。
[完整清单](ubuntu/release.json)记录 27 个已装配组件，包含修复后的 `winebth.so`；现有 -5 DEB 使用 ABI 112。
主程序使用 X11/XWayland。CEF 修订针对固定版本的厂商 x86 DLL，回补 V8 保护模式和光标坐标处理，
邮件进程通过该 prefix 的 IFEO DPI 设置与主界面配合。

## 构建 DEB

`package.py` 从已校验的公开基包取得未登录模板，再装配官方安装器、Wine 和助手。
Wine PE 调试信息会被剥离，同时检查运行时 section 保持一致；厂商 DLL 保持原样。
包内重复文件去重，创建用户目录时解除硬链接。

```sh
python3 ubuntu/package.py \
  --base-package /absolute/com.qq.wecom.spark_5.0.12.6018-3.preview20261025_amd64.deb \
  --runtime /absolute/verified-wine-runtime \
  --helpers /absolute/verified-helpers \
  --wine-source /absolute/wine-11.20.tar.gz \
  --installer /absolute/WeCom_5.0.13.6005.exe \
  --stage /absolute/new-stage \
  --output /absolute/com.qq.wecom.spark_5.0.13.6005-5_amd64.deb
```

自行构建后，更新 `release.json` 的组件指纹再打包。原始安装器、运行库及字体来源在 `materials/` 中记录。
回归入口和完整场景清单见[测试说明](ubuntu/wine-x11-fix/tests/README.md)。
