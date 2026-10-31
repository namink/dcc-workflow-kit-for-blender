# DCC Workflow Kit 0.1.2 · Blender 4.5 兼容预览版

- 扩展最低版本由 5.1.0 调整为 4.5.0，上限保持 <5.3.0，源码 bl_info 同步更新。
- Windows Blender 4.5.10：45 项源码检查通过，覆盖生命周期、跨模式数据、RP IK、故障恢复、保存重开、中文、GUI 和多窗口切换。
- 未修改运行时逻辑。5.1.0 / 5.2.2 沿用 0.1.1 验证，5.0 尚未实测；全部命令和生产场景尚未全量验收。

下载 dcc-workflow-kit-0.1.2.zip，通过“从磁盘安装”安装。先停用独立的 Blender Max / Maya Workflow Kit。请勿将 source.zip 作为扩展安装包。

---

# DCC Workflow Kit 0.1.1 · 整合汉化预览版

一个 Blender 扩展，可在偏好设置中选择 **3ds Max + Blender** 或 **Maya + Blender**，并通过顶栏或 `Ctrl+Alt+Shift+M` 切换。

- Max 与 Maya 交互互斥启用；切回 Blender 保留必要场景求值服务。
- 普通模式切换保留物体、材质、单位、帧率和帧范围；新建场景为独立操作。
- Max 中文词典 2,652 条，Maya 中文词典 9,773 条；本轮扫描识别的显示文本及注册原生标签已补齐，保留产品名、快捷键、内部命令及用户名称。
- 已在 Windows 的 Blender 5.1.0 / 5.2.2 完成选取的语言、注册生命周期、跨模式数据及界面检查。

安装：先停用单独安装的 Blender Max / Maya Workflow Kit，再在 Blender“获取扩展 → 从磁盘安装”中选择 `dcc-workflow-kit-0.1.1.zip`。下载源码请使用仓库源码或 `-source.zip`，不要将源码 ZIP 当作插件安装包。

这是预览版，尚未对两个上游插件全部命令、所有场景状态及译文逐项人工验收。具体边界见 README.md、LOCALIZATION_REPORT.md、VALIDATION.md。

基于 Blender Max 0.6.8、Maya Workflow Kit 0.6.2 及 namink 的简体中文本地化。代码 GPL-3.0-or-later；Maya 部分原始非代码资产按原 CC0 声明保留。原作者及许可见 THIRD_PARTY.md。
