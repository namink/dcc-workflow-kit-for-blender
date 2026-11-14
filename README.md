# DCC Workflow Kit 0.2.1 · 简体中文预览版

只需安装一个 ZIP，包含 MaxFlow 0.8.3 和 Maya Workflow Kit 0.16.0。此构建面向 Windows Blender 5.3.0；Blender 4.5 请保留 DCC 0.1.5。

1. 停用独立安装的 Blender Max / MaxFlow 和 Maya Workflow Kit，避免同名操作冲突。已有工具架或快捷键时建议先备份。
2. 在 Blender 5.3 的「编辑 → 偏好设置 → 扩展」右上角菜单选择「从磁盘安装」，选中 dcc-workflow-kit-0.2.1.zip，无需解压。
3. 在「插件 → DCC Workflow Kit」中选择「3ds Max + Blender」或「Maya + Blender」。用顶部按钮切换，也可使用 Ctrl+Alt+Shift+M。
4. 在「偏好设置 → 界面」选择简体中文，开启「翻译界面」；也可开启「翻译工具提示」。

## 本次更新

- MaxFlow：保留原 DCC / 3ds Max 术语，补译编辑多边形层等新版界面与提示，并为中文自绘控件使用 Blender 字体。
- Maya：合并最新版简体中文词表和 DCC 原有术语，补译选择工具设置、帮助行、大纲视图及蓝铅笔等；保留用户自定义的物体、骨骼及工具架名。
- Blender 5.3：适配大纲视图的排序接口，使用 5.3 行业兼容键表并修复三个已失效的操作符绑定。
- 切换工作流由 DCC 统一管理；场景数据和工作区保留，只有交互模式切换。Maya 设置可在插件偏好设置中导入、导出。

上游作者及授权见 THIRD_PARTY.md。下游验证范围见 VALIDATION-5.3.md。未逐项验收全部建模、绑定、动画、渲染工具，也未测试其他平台。
