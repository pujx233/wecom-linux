# 图片预览阴影输入回归

`policy.c` 在独立 Wine prefix 中创建真实窗口并运行实际的 `titlebar-managed.exe`，不模拟 Wine API。
ImagePreview 是无 owner 的普通顶层窗口；它的 PerryShadowWnd 才是 owned popup，避免把预览错误建成对话框。

```bash
python3 run.py --runtime /path/to/wine --candidate /path/to/titlebar-managed.exe \
  --baseline /path/to/old/titlebar-managed.exe --output /path/to/new-result-directory
```

需要 MinGW、Xvfb、xauth 和 xwininfo。已有 `policy.c` 编译结果时可用 `--fixture` 传入。
测试使用自己的 Xvfb、Xauthority、XDG runtime 目录和无账号 prefix，不连接宿主桌面。

两种 `WINE_X11_OWNED_FRAME` 模式都检查：主窗口阴影仍然穿透，新增的预览阴影也穿透；
其他 owner、非 layered 阴影、交互窗口、预览标题栏、子窗口以及跨进程 owner/阴影均不修改。
窗口普通 style 和矩形必须保持不变。批量创建 24 个独立预览阴影，核对全部处理且诊断结束摘要完整。
watch 模式还检查新建预览阴影在下一次一秒轮询前被 SHOW hook 处理。
随后连续创建 32 个可见阴影，让应用线程在首次 `WM_STYLECHANGING` 中停留 750 毫秒，
覆盖助手等待跨进程窗口调用时再次进入 SHOW 回调的路径。
持续读取输出管道，核对所有阴影均完成处理、33 组诊断完整，并逐窗口检查前后记录配对。
33 组包含前面的单窗口 SHOW 用例；修复前的逐窗口 flush 版本会在此丢失、混杂日志。

真实客户端另需验证：OCR 文字可用鼠标选择并复制，最大化/恢复、标题栏拖动、边缘缩放和关闭仍正常。
隔离策略测试不等价于 reporter 的 niri/Mutter 环境已完整复现。
