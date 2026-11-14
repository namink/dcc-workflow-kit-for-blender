# DCC Workflow Kit 0.2.1 · 简体中文修订

- Maya：挤出等视图内编辑器、UV 统计和超图现在跟随界面语言。挤出字段按 Autodesk 简体中文文档使用「厚度」「局部平移 Z」「偏移」「分段」「保持面的连接性」。
- 3ds Max：统一「桥接」「沿样条线挤出」「子对象层级」「修改器堆栈」等建模用语，补译编辑多边形提示、快捷键参考及帮助菜单。

术语参考：[Maya 挤出选项](https://help.autodesk.com/cloudhelp/2024/CHS/Maya-Modeling/files/GUID-0026EDC2-E6F7-4C57-A22F-CA6D440CE4AD.htm)、[Maya UV 视图菜单](https://help.autodesk.com/cloudhelp/2022/CHS/Maya-Modeling/files/GUID-E9FE00F2-5B8B-4224-9E96-878E9FBAA466.htm)、[3ds Max 编辑多边形修改器](https://help.autodesk.com/cloudhelp/2026/CHS/3DSMax-Modifiers/files/GUID-1230619A-8CB3-4411-B07D-C133716F61F9.htm)、[3ds Max 可编辑多边形](https://help.autodesk.com/cloudhelp/2024/CHS/3DSMax-Modifiers/files/GUID-FF7D7633-03AD-4427-821A-65F8AC484CDD.htm)。

# DCC Workflow Kit 0.2.0 · Blender 5.3 试用版

- 更新到 MaxFlow 0.8.3 和 Maya Workflow Kit 0.16.0，补充编辑多边形、工具设置和帮助栏的简体中文。
- 适配 Blender 5.3 的大纲视图排序接口及行业兼容键表，修复三个失效的快捷键绑定。
- 在 Windows Blender 5.3.0 验证 ZIP 安装、两套工作流切换和界面语言切换。详见 [验证记录](VALIDATION-5.3.md)。
- 安装包为 `dcc-workflow-kit-0.2.0.zip`。Blender 4.5 继续使用 0.1.5。

# DCC Workflow Kit 0.1.5 · 视口撕下副本修复预览版

支持 Blender >=4.5.0、<5.3.0。安装文件为 dcc-workflow-kit-0.1.5.zip，先停用独立 Max/Maya 插件，安装后重启 Blender。

- 修复 Maya“撕下副本”传入 VIEW_3D 时枚举缺失；复制当前视口并保留视图状态。4.5.10 实际新窗口调用验证通过。
- 包含本地 0.1.4 快捷键调整：Screen 全局绑定及 3D View 优先绑定，明确 TOGGLE。真实键盘触发尚未确认修复。
- 延续 0.1.3 的统一工作流菜单与旧操作符防护。

验证：Windows Blender 4.5.10 回归 46/47 项通过；344 个 Python、4 个 JSON 及 ZIP 完整性通过。其他版本本轮未重测。

已知问题：新增 3D Viewport 标签缺中文词条，导致一项语言回归失败；Maya 上游键位含 objectshaderfx_copy、text.uncomment、clip.graph_select_all 三个无效操作符，尚未修复。长按、热盒及真实键盘交互未全量验收。本版供实测，不作为完整生产验收声明。
