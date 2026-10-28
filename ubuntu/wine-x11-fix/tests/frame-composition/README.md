# 原生合成与弹窗输入回归

这两项实验使用合成像素和测试窗口，不运行企业微信，不读取个人账号。GNOME、Xwayland、
PipeWire、D-Bus、Wine prefix 与配置都在独立目录和私有会话中运行，测试结果写入该目录。
输入测试只向私有虚拟显示器发送鼠标事件。退出时先关闭私有 Mutter，再清理其子进程。

需要 GNOME Shell/Mutter、Xwayland、PipeWire 命令行工具、GStreamer 的 PipeWire/PNG 插件、
Python 的 PyGObject/Pillow，以及 `x86_64-w64-mingw32-gcc`。使用完整的私有 Wine WoW64 runtime。

```sh
export WECOM_QA_ROOT=/absolute/disposable/wecom-frame-qa
mkdir -p "$WECOM_QA_ROOT"
touch "$WECOM_QA_ROOT/.wecom-frame-qa"
cp -a /absolute/private-wine "$WECOM_QA_ROOT/wine"
python3 run-foreign-frame.py
python3 run-popup-input.py
```

运行前，该目录中不能有其他测试进程。不存在 prefix 时，脚本在私有显示器中执行 wineboot。
不要复制已登录的企业微信 prefix。`.wecom-frame-qa` 标记是对可丢弃测试目录的明确确认。

`run-foreign-frame.py` 创建静止的主窗口和分层装饰，再让另一个进程绘制红、蓝内容。
它同时检查 GDI 读回、原生源 pixmap 和桌面合成后的像素，防止把“已经画进后台位图”误判为“用户已经看到”。
共绘制八次；第五次由原生 resize 引起的 Win32 状态同步触发，应用在该回调中等待外部绘制并重入消息循环。
旧版会消费合成通知却丢掉更新，源已变红而桌面仍显示上一次的蓝色。修订后，解锁会重新提交待合成内容。
源像素在桌面检查结束后读取，避免读回影响可见性判定。每次更新超过一秒仍未显示即失败。

`run-popup-input.py` 使用独立 X11 窗口接收穿透事件。普通工具弹窗和非分层透明工具弹窗必须
各收到三组完整点击，底层窗口不能收到事件；分层透明窗口则必须允许六个按下/松开事件穿过。
弹窗临时改变激活样式时，原生窗口身份也必须保持不变。
它还检查头像式 owned 预览在其 owner 上方，以及两个带共享框架的同 owner 窗口能按明确请求往返换序。
首次映射后的顺序以稳定后的 Win32 枚举为准，避免将窗口管理器激活顺序当作绘制错误。

两个脚本输出 JSON 和截图，记录实际驱动 SHA256。失败时退出码为 1。
这两项用于验证底层机制；真实企微的邮件、图片、分享记录和成员卡仍需要单独验收。
