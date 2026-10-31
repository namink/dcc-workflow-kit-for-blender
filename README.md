# DCC Workflow Kit · 整合预览版 0.1.1

一个 Blender 扩展，按用户习惯选择 **3ds Max + Blender** 或 **Maya + Blender**，通过顶栏在所选工作流与 Blender 之间切换。

基于 Blender Max 0.6.8 与 namink 的 Maya Workflow Kit 0.6.2+zh.2 中文版。作者、许可证与修改记录见 [THIRD_PARTY.md](THIRD_PARTY.md)。

0.1.1 的汉化补全范围、词条统计和保留原文规则见 [汉化检查记录](LOCALIZATION_REPORT.md)。

## 安装与使用

当前开发和验证环境为 Windows、Blender 5.1.0 / 5.2.2。扩展清单限定 Blender 5.1–5.2；其他系统尚未验证。

1. 先停用单独安装的 Blender Max、Maya Workflow Kit（包括中文版本）；它们与本扩展沿用同一批内部操作符 ID，不能同时启用。
2. 在 Blender 的“编辑 → 偏好设置 → 获取扩展”右上角菜单选择“从磁盘安装”，从 [Releases](https://github.com/namink/dcc-workflow-kit-for-blender/releases) 下载并安装 `dcc-workflow-kit-0.1.1.zip`，不要选择 GitHub 自动生成的源码 ZIP。
3. 在本扩展的设置中选择“工作流组合”：`3ds Max + Blender` 或 `Maya + Blender`。
4. 通过顶栏右侧的 `Blender / 3ds Max` 或 `Blender / Maya` 切换。快捷键为 `Ctrl+Alt+Shift+M`。
5. 如需启动时进入所选工作流，将“启动界面”设为“所选工作流”；默认启动为 Blender。

更换工作流组合会回到 Blender，双方的配置分别保存。切换时不自动新建场景、删除默认物体、更改帧率/帧范围或套用场景单位。Maya 的新建场景仍是独立命令，其保存提示沿用原版。

中文跟随 Blender 的“简体中文”及“翻译界面”设置。关闭界面翻译或切回英文即可恢复英文显示。用户对象名、材质名、脚本、路径和内部标识不参与显示翻译。

## 实现范围

- 单一扩展 ID：`dcc_workflow_kit`；统一偏好设置、顶栏开关与切换状态。
- Max / Maya 界面与快捷键互斥启用；失败清理并返回 Blender，设置页显示原因。
- 场景数据定义及必要求值服务与 UI 分离。Maya RP IK 等求值服务和 Max 参数化对象在切回 Blender 后继续工作。
- 复用两套工作区，返回用户原 Blender 工作区；保留已经追加的工作区以支持再次切换和自定义。
- Max 循环边选择适配 Blender 5.1/5.2；时间栏布局禁用直接修改 Blender 内存指针的路径，采用可退化的公开操作。
- Max 已接入原生 UI、自绘文字、文本测量、中文字体回退及动态消息模板。上下文词条与 Maya 分离。

## 当前限制

这是可测试的整合预览版，不是经过全量生产验收的稳定版。Max 中文目录当前 2,652 条，Maya 中文目录当前 9,773 条。本轮已补齐静态扫描识别的显示文本、缺失提示及实际注册的原生标签；已知专业术语按 Max/Maya 分开处理，其余文本提供通顺中文译法。产品名、快捷键、文件格式、命令和用户数据保留原文。部分词条经翻译初稿及术语校正完成，尚未对所有场景和控件状态逐一进行人工视觉验收。

现有测试覆盖注册/注销、反复切换、核心界面、跨模式参数化对象与 RP IK、保存重开、翻译开关和失败恢复；未宣称对两个原插件的全部命令、材质/渲染器、绑定和全部动画工作流逐一回归。

选择工作流是进程级设置。暂不支持同一 Blender 进程中两个窗口分别使用 Max 和 Maya 两套交互。用户实际场景仍依赖 Blender 数据与原插件功能范围；不会因此获得 `.max`、`.ma`、`.mb` 原生文件支持。

切回 Blender 仍保留必需的求值服务；停用整个扩展会停止这些 Python 服务，依赖它们的场景需要重新启用扩展才能继续按原规则更新。

旧插件数据标识保留，便于读取旧文件。只有能直接读取到的原偏好设置会被复制；旧扩展用户工具架文件不会被删除。请先备份并通过设置中的导入入口复制旧工具架；没有找到源文件时保留当前工具架。

## 从源码构建

```powershell
python tools/build.py
```

输出位于 `dist/`，ZIP 根部直接包含 `blender_manifest.toml`。源码在 `src/dcc_workflow_kit`；测试在 `tests`；本地运行后的结果和界面截图在 `test-results`；公开验证摘要位于 `validation/summary.json`。本轮汉化盘点、逐条补译及术语校正记录在 `localization-review`。开发测试必须使用独立的 Blender 用户配置和工厂启动，不要将测试脚本运行在正在工作的场景里。

修改 Max 译文：编辑 `src/dcc_workflow_kit/locales/max_zh_HANS.json` 后重新构建。术语补充与初始来源记录在 `terminology`。Maya 词条仍在其后端的 `translations_zh_HANS.json` 中。仅翻译显示文本，不修改内部命令、属性名或枚举标识。

## 术语参考

- [3ds Max：修改器堆栈及四元菜单](https://help.autodesk.com/cloudhelp/2026/CHS/3DSMax-Basics/files/GUID-8209526B-B4EC-406D-A3E2-D43EA717A28A.htm)
- [3ds Max：命令面板与修改面板](https://help.autodesk.com/cloudhelp/2026/CHS/3DSMax-Modifiers/files/GUID-4BC9EEAC-3B33-4D71-926B-DE843FC23C8A.htm)
- [Maya：通道盒与属性编辑器](https://help.autodesk.com/cloudhelp/2026/CHS/Maya-Basics/files/GUID-4C954FB2-8B6A-4BBD-9695-DF432616D0D2.htm)
- [Maya：构建历史](https://help.autodesk.com/cloudhelp/2026/CHS/Maya-Basics/files/GUID-503E227B-EF49-4A78-B3CA-7EAC588017C9.htm)
- [Maya：冻结变换与枢轴](https://help.autodesk.com/cloudhelp/2026/CHS/Maya-Basics/files/GUID-378D7FF6-492F-4DA4-A468-507E6ABF8B58.htm)
