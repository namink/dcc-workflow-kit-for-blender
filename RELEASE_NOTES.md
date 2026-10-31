# DCC Workflow Kit 0.1.5 · 视口撕下副本修复预览版

支持 Blender >=4.5.0、<5.3.0。安装文件为 dcc-workflow-kit-0.1.5.zip，先停用独立 Max/Maya 插件，安装后重启 Blender。

- 修复 Maya“撕下副本”传入 VIEW_3D 时枚举缺失；复制当前视口并保留视图状态。4.5.10 实际新窗口调用验证通过。
- 包含本地 0.1.4 快捷键调整：Screen 全局绑定及 3D View 优先绑定，明确 TOGGLE。真实键盘触发尚未确认修复。
- 延续 0.1.3 的统一工作流菜单与旧操作符防护。

验证：Windows Blender 4.5.10 回归 46/47 项通过；344 个 Python、4 个 JSON 及 ZIP 完整性通过。其他版本本轮未重测。

已知问题：新增 3D Viewport 标签缺中文词条，导致一项语言回归失败；Maya 上游键位含 objectshaderfx_copy、text.uncomment、clip.graph_select_all 三个无效操作符，尚未修复。长按、热盒及真实键盘交互未全量验收。本版供实测，不作为完整生产验收声明。
