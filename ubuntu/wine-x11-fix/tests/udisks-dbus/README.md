# UDisks 订阅边界回归

```sh
python3 run-match.py --source /absolute/wine-source/dlls/mountmgr.sys/dbus.c --out /absolute/new-result-dir
```

需要 `cc`、`pkg-config`、libdbus 开发文件和 `dbus-run-session`。脚本从指定生产源码提取订阅规则及
`udisks_filter`，启动新的私有 D-Bus daemon 和三个独立连接，不运行 Wine，不连接宿主系统总线。
设备操作端点替换为计数器，因此能验证消息是否送达、是否进入刷新或移除路径，不会操作真实磁盘。

16 项检查覆盖：无关发送者的 128 条消息、错误路径、路径前缀碰撞、错误成员名，合法属性变化和失效，
接口添加/移除，UDisks2 服务名称换主后的新旧发送者，以及 UDisks1 回退的添加/变化/移除。
每个用例由同一发送者在待测信号之后发送定向 barrier；收到 barrier 才判定结果，不以固定等待时间
推断“没有收到”。报告保存实际投递数、刷新/移除次数、生产源码和夹具指纹。

同一测试应对修改前源码运行负例：旧规则会把无关发送者的 128 条属性通知变成 128 次刷新调用。
这不测量真实 `GetManagedObjects` 的耗时，也不验证实际设备枚举、挂载或 Windows 盘符。
本修复保留 UDisks 域内原有处理；Drive 属性变化未传播到关联 Block 的旧行为不在此次修改范围内。
