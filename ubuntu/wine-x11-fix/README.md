# Wine 11.20 企业微信修订

当前源码对应企业微信 5.0.13.6005-6 测试版。
[组件清单](../release.json)、[测试结果](../validation.json)及[实现 review](CODE-REVIEW.md)分别记录构建、运行与验证状态。

## 实现

主体、标题和阴影共用原生外框，附属层按 owner 的同一坐标快照提交。
几何确认、像素上传与 XSync 完成计数形成同一绘制事务。
子窗口绘制提交会通知顶层外框，跨进程提交先同步像素上传，再通知外框所属进程；XDamage 继续处理原生绘制变化。
窗口层级、焦点协议、形状裁剪和显示原点分别使用原生窗口状态处理。

适配器声明 `WINE_X11_FRAME_ATTACHED_CLASSES='PerryShadowWnd;TitleBarWindow'`，
由 `WINE_X11_FRAME_DECORATION_CLASSES=PerryShadowWnd` 指定主体后方的装饰层。
成员卡和独立弹窗保留各自的坐标及层级。

其余修订包括输入法候选锚点、文件选择与文件管理器接口、剪贴板文件 URI、字体、
GDI+ 采样、设备关系查询和 UDisks 通知。-5 还调整了升级启动与最大化窗口的全屏判定。
后续源码修复了仅 Wine 后台驻留时的升级切换，并调整窗口状态与布局提交的时序。
具体因果和保留问题见 [CODE-REVIEW.md](CODE-REVIEW.md)。

文件对话框补齐初始目录通知，并根据 COM 回调所需的接口选择实现。
需要 Windows Shell View 的调用使用原有 Wine 文件窗口；普通 `IFileDialog` 调用继续使用 Portal。
回退前保留当前目录并清理选择结果，优先遵守回调中的取消，重用对话框时重新检查所需接口。

邮件正文的 `Chrome_WidgetWin_0` 与外层 Qt 窗口分属不同进程。
原生 XIC 属于外层线程，组合输入现按实际焦点传到正文进程，并使用不含指针的 UTF-16 消息载荷；
候选坐标回到 XIC 所属线程设置。过期焦点的消息丢弃，完成和取消同时重置原生预编辑状态。
失焦也结束对应的原生组词；缓冲和重置状态按 XIC 独立保存，避免清掉另一个窗口的输入。
新焦点没有自己的 Windows composition 时，清除共享原生引擎带来的上一窗口组词。
XIM 的空开始回调不再生成立即结束的 Windows composition；重置后的旧结束回调也不再取消新输入。
完整消息泵会检查 Xlib 已缓存的事件，最终 flush 后仍有缓存事件时继续处理，避免等待已无新数据的 fd。

本版 CEF 107 默认选择 TSF，不能消费这条 IMM32 输入路径。
Ubuntu 启动器默认通过其正式开关 `--disable-features=TSFImeSupport` 选择 IMM32，
同时关闭旧的 `WM_CHAR` 输入桥；`WECOM_CEF_IME_FIX=0` 可保留 CEF 原选择。
新路径启用时不会加载旧桥，即使环境仍保留 `WECOM_IME_FIX=1`。
对照旧路径时须同时设置 `WECOM_CEF_IME_FIX=0 WECOM_IME_FIX=1`。
通用 Arch 启动器保留旧版 Wine 的默认行为，使用修补后的整套运行库时才显式启用该开关。
本机邮件正文、主题、聊天之间的组词切换，以及换行、取消、中英文切换和最大化还原后的候选定位已实测；
这不包含 IBus 重启后的前端自动恢复，宿主问题见 [IBus 说明](../host-ibus/README.md)。

图片预览的同进程 layered 阴影纳入既有穿透策略，并在 SHOW 事件时处理；预览本体保留移动和缩放。

原生外框 resize/Expose 时直接提交已完成的合成缓冲，修复重定向子窗口遮蔽背景后出现的旧画面和黑区。
嵌套子窗口的提交按 `GA_ROOT` 找到外框所属窗口，复用既有合并队列，补齐文档正文已更新而外框保持旧尺寸的通知缺口。
合成过程另处理子窗口跨连接隐藏、销毁及 InputOnly 窗口，避免使用未创建的 pixmap 或无效 Shape 结果。
这些修订仍未发布。#5 的真实文档首页在 KWin 双缩放环境完成三轮最大化、还原和跨屏拖动，未再出现持续旧画面。
#4 的 GPU 重置触发请求，以及 #5 reporter 的完整黑框拖动现象仍未确认。

## 会议组件

会议插件的 `wemeet_platform.dll` 静态导入 `SLWGA.dll!SLIsGenuineLocal`。
Wine 11.20 缺少该模块，会使 `wemeet.dll` 加载失败。补丁增加双架构 Wine 内建模块和对应导出。
尚未实现的正版状态查询返回 `E_NOTIMPL`，不改写输出状态，不伪造成功；缺少必需参数返回 `E_INVALIDARG`。
调用方按其原有错误处理继续启动。模块契约与真实会议启动分别验证，详见[测试说明](tests/software-licensing/README.md)。

## CEF 内存

32 位 `libcef.dll` 的代码和只读数据包含大量重定位地址。
Wine 服务端按共同的重定位基址生成一次缓存，封存后交给各进程以写时复制方式映射。
客户端保留独立的可写数据和导入修复；最后一个映射卸载后释放缓存。
缓存不可用、镜像布局不适用或包含不支持的只读段重定位时，继续使用原有加载路径。

Ubuntu 启动器默认启用 `WECOM_SHARED_CEF_IMAGE=1`，并在第一次启动 Wine 服务前传入。
设置 `WECOM_SHARED_CEF_IMAGE=0` 可关闭此优化。修改开关或替换运行库后，需要完整退出企业微信及其私有 Wine 进程。

`WECOM_SHARED_PE_IMAGE=1` 进一步为其他 x86/x64 模块提供只读节缓存。
节在文件中的偏移未按内存页对齐时，原加载器会整段读入匿名私有内存；
缓存将这些节按页排列，保留共同的 DLL 重定位，并让客户端按需以写时复制方式映射。
可写数据、导入修复和地址冲突后的额外重定位继续由各进程独立完成。

这部分缓存使用 prefix 所在磁盘上的匿名临时文件，只向客户端发布只读描述符，
干净页可以回收后从文件重读，不依赖 swap。最后一个映射卸载时文件随描述符关闭而删除。
建立可写映射前，先为缓存头和只读缓存节预留磁盘空间，覆盖节内的零填充区域；
分配失败时关闭临时文件，继续原有加载路径，避免稀疏文件写入过程中磁盘耗尽触发 `SIGBUS`。
tmpfs、noexec、磁盘空间不足、可写共享节和不支持的重定位布局继续使用原加载路径。
原始 EXE/DLL 不改写；Ubuntu 启动器默认开启，`WECOM_SHARED_PE_IMAGE=0` 可关闭。

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
