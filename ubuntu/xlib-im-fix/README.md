# 私有 Xlib 的 XIM 回调修复

Xlib 在 `XSetICValues` 和 `XResetIC` 的同步应答期间把输入法回调放入 IC 的 pending 队列。
原实现解除 `waitCallback` 后没有派发，必须等另一个回调到达才会处理旧队列。
真实企微中，IBus 已绘制“你好”，Wine 的 HIMC 却仍保留更早的“你哈”，失焦因此提交旧词。

补丁在同步请求的结果解析和临时缓冲清理完成后派发队列。
派发前取出队首，客户端回调重入时继续排队，保持 FIFO；回调销毁 IC 时释放余下队列，
通过回调栈上的生存标记停止访问已销毁 IC。正常即时回调继续使用无需分配的路径。

构建基于 Ubuntu `2:1.8.13-1ubuntu0.1`，先校验两个源码归档的 SHA-256，
依次应用发行版九项补丁和本补丁。源码与发行版许可保留在精确源码包中。

```sh
python3 build.py --output /absolute/new-output
```

依赖 C 编译器、make、patch、pkg-config、Xorg 协议头、xtrans 和 libxcb 开发文件。
输出 `libX11.so.6` 放在 Wine 的 `lib` 目录，`winex11.so` 的 RUNPATH 为 `$ORIGIN/../..`。
此路径只影响私有 Wine 驱动，不设置桌面全局 `LD_LIBRARY_PATH`。
`tests/run-xim-callbacks.py` 覆盖真实协议队列、重入与销毁。
