# xwayland-satellite 中文标题

xwayland-satellite 0.8.2 和 0.8.3 的客户端装饰只用一个 Open Sans 字体，缺少字形时没有回退。
这条额外的 25 像素标题栏不属于 Wine，修改 Wine 的 Tahoma 或 CaptionFont 不能补齐它。

此补丁基于上游 v0.8.3（b83eab900644e4c7c77982ce3d44cb490f0c5e1d），保留原字体，
缺字时按 Fontconfig 的排序选择覆盖该字符的字体，支持 TTC face index，并按需缓存字体。
绘制按目标边界裁剪。它不区分应用、标题或字符语言。

```sh
git checkout v0.8.3
patch -p1 < /absolute/path/font-fallback.patch
cargo test --locked --lib --features fontconfig
cargo build --locked --release --features fontconfig
```

系统仍需安装覆盖中文的字体，例如 Noto Sans CJK。未启用 fontconfig 时保留上游嵌入字体行为。
补丁已在隔离的 Fedora/niri 测试容器部署，包含保留登录的主 XWayland 实例。
不替换宿主桌面组件，也不随企业微信包自动接管系统桥接器。
Wine 的原生文件窗口集成与这个补丁相互独立。

验证包含：原版四个中文字符均为同一缺字方块，补丁后为四个有效字形；英文标题像素不变；
不同缩放与小尺寸的边界裁剪；上游全部单元测试。真实标题截图保存在本地 QA 报告中。

[上游源码](https://github.com/Supreeeme/xwayland-satellite/blob/v0.8.3/src/server/decoration.rs)
采用上游 MPL-2.0 许可证，见 LICENSE。
