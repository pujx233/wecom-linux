# Ubuntu 使用与验收边界

当前交付为企业微信 5.0.12.6018 / 私有 Wine 11.20 的预览包，2026-10-25。
验证环境：Ubuntu 26.04.1、GNOME 50.1 Wayland、XWayland、两块 200% 显示器、IBus/Rime。
包名 `com.qq.wecom.spark`，桌面名称“企业微信”。不需要额外桌面或任何 GNOME 系统修订。

## 运行目录

程序和模板：`/opt/apps/com.qq.wecom.spark/files`。
用户 prefix：`${XDG_DATA_HOME:-$HOME/.local/share}/wecom/prefix`；日志在相邻的 `logs` 目录。
首次启动只复制从未登录过的模板，不复制维护者的在线 prefix。
用户目录按当前 Linux 用户重定位；不连接维护者的 home。系统 Wine 与其他 Wine 应用不受影响。

## 当前修订

Wine 的透明窗口、输入区域、窗口关系、跨进程 DC、绘图提交及 SNI 修改整合为
`ubuntu/wine-x11-fix/wine-11.20-x11-popups.patch`，直接适用于原始 Wine 11.20。
四个组件 wineserver、win32u.so、winex11.so、x64 explorer.exe 必须配套；不能只替换其中一个。
固定 SHA256 与对应源码哈希见 release.json 和 validation.json。

聊天记录白帧有两条提前提交路径：获取 DC 被误认为绘制完成；Wine 内部光标反色更新又提前释放 DC。
现在应用实际写入后的 ReleaseDC 或 EndPaint 才能完成提交；读取、内部光标和有效像素迁移不作完成信号。
已完成内容立即刷新，不等待下一次消息循环。没有按像素颜色、固定延时或企微窗口名隐藏白帧。
这项修订没有实现 NtGdiFlush 的其他功能，也不能据此声称所有 GDI 场景都已修复。

邮件通过私有 prefix 的 WeMail.exe IFEO dpiAwareness=1 与主进程统一 DPI 模式。
CEF 固定原始 SHA256 后回补 V8 PAGE_WRITECOPY 兼容和旧 Chromium WindowFromPoint 坐标修订。
它改变了原厂 CEF DLL，原有 Authenticode 签名不再有效，企业微信 WXWork.exe 未修改。

## 实际结果和限制

- 当前绘图组合：SNI 路线 4 次重启后的首次聊天记录开/关、1 次连续开/关均未采到白帧。
- 桌面快捷方式实际启动路线也已复测；截图和录像是异步采样，不能保证覆盖全部帧。
- 右键、独立聊天窗口切换、邮件光标有通过样本，仍未覆盖全部弹窗和状态组合。
- 已知托盘“更多操作”使用居中回退，单击/右键语义不完整。本次保留失败，没有发布为稳定版。
- XEmbed 替代方案在顶栏位置变化后仍偏移 124 物理像素，已回退，不包含在发布组合。
- 头像/成员卡、已读人数面板、标题栏、最大化/展开/聊天记录的全部过渡仍需继续验收。
- 附件收发、审批、音视频及其他 Linux 桌面未全面验证，不使用测试通过标签暗示兼容。

## 构建和打包

Wine 完整源码归档 SHA256 为
`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`，
来源为 `https://github.com/wine-mirror/wine/archive/refs/tags/wine-11.20.tar.gz`。
依赖和构建命令见 `ubuntu/wine-x11-fix/`。
基础 prefix 来自官方企微安装器与运行库安装后、首次账号登录前保存的副本。
打包脚本必须核对该副本的逐文件清单，再覆盖明确列出的私有 Wine 组件、助手和 CEF 修订。
不要将任何已经登录过的 prefix 作为 --baseline。

```sh
python3 ubuntu/package.py --help
bash ubuntu/build-helpers.sh /absolute/helper-output
sh ubuntu/wine-x11-fix/build.sh /absolute/wine-11.20.tar.gz /absolute/new-build
```

原始安装、运行库与字体材料记录保存在 materials/，不是所有文件均可重新分发。
字体和厂商运行库按原许可使用；完整 Wine 源码和本次修改随包提供。

## 清理缓存后重建

保留源码和最终 DEB 即可重建私有 Wine，不需要保留旧构建目录或已登录 prefix。
`package.py` 记录原发行时的严格预登录基线检查；该历史基线没有单独分发。
公开包的未登录模板可直接从最终 DEB 提取，再替换重建的四个 Wine 组件：

```sh
wecom_rebuild_dir=/absolute/new-rebuild
mkdir -p "$wecom_rebuild_dir"
dpkg-deb -R ./com.qq.wecom.spark_5.0.12.6018-3.preview20261025_amd64.deb \
  "$wecom_rebuild_dir/package"
cp "$wecom_rebuild_dir/package/usr/share/doc/com.qq.wecom.spark/wine-11.20.tar.gz" \
  "$wecom_rebuild_dir/wine-11.20.tar.gz"
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v "$wecom_rebuild_dir:/work" \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/wine-build

wecom_payload="$wecom_rebuild_dir/package/opt/apps/com.qq.wecom.spark/files"
install -m 755 "$wecom_rebuild_dir/wine-build/build/server/wineserver" \
  "$wecom_payload/wine/bin/wineserver"
for component in win32u winex11.drv; do
  case "$component" in win32u) library=win32u.so ;; *) library=winex11.so ;; esac
  install -m 755 "$wecom_rebuild_dir/wine-build/build/dlls/$component/$library" \
    "$wecom_payload/wine/lib/wine/x86_64-unix/$library"
done
for destination in wine/lib/wine/x86_64-windows/explorer.exe \
  template/drive_c/windows/explorer.exe template/drive_c/windows/system32/explorer.exe; do
  install -m 755 "$wecom_rebuild_dir/wine-build/build-explorer/programs/explorer/x86_64-windows/explorer.exe" \
    "$wecom_payload/$destination"
done
dpkg-deb --root-owner-group -Zxz --build "$wecom_rebuild_dir/package" \
  "$wecom_rebuild_dir/wecom-rebuilt.deb"
```

上述命令保留未登录应用模板，只重建 Wine；不同工具链不保证二进制哈希一致。
若修改源码后再发行，必须同步包内对应补丁、版本、组件哈希及验收记录，不能沿用本发行的通过结论。
它也不代表从零重现第三方安装器和字体材料的整个安装过程。
