# 0.1.7 Blender 4.2 Maya 空格切换修复

修复短按空格进入四视图后无法返回单视图。对不支持坐标合并区域的 Blender 使用原生区域最大化；单视图暂时隐藏周围面板，再按空格恢复。Blender 4.2.9 GUI 操作符四轮往返通过，真实键盘事件未模拟，其他工具未完整重测。

安装包：`dist/dcc-workflow-kit-0.1.7-blender-4.2.zip`。本次为 4.2 兼容分支，主分支 0.2.1 面向 Blender 5.3。

# 0.1.6 Blender 4.2.9 compatibility preview

Native 4.2 keymap snapshot, legacy workspace format and Properties panel roles, legacy sculpt/weight brushes, Angle Based UV fallback, missing Chinese label, and selective upstream docs/operator detection fixes. Latest Maya 0.21.0 and MaxFlow 0.8.5 features are not fully merged; both require Blender 5.0+. See COMPATIBILITY_42.md.

# DCC Workflow Kit 0.1.5 · 视口撕下副本修复预览版

支持 Blender >=4.5.0、<5.3.0。安装文件为 dcc-workflow-kit-0.1.5.zip，先停用独立 Max/Maya 插件，安装后重启 Blender。

- 修复 Maya“撕下副本”传入 VIEW_3D 时枚举缺失；复制当前视口并保留视图状态。4.5.10 实际新窗口调用验证通过。
- 包含本地 0.1.4 快捷键调整：Screen 全局绑定及 3D View 优先绑定，明确 TOGGLE。真实键盘触发尚未确认修复。
- 延续 0.1.3 的统一工作流菜单与旧操作符防护。

验证：Windows Blender 4.5.10 回归 46/47 项通过；344 个 Python、4 个 JSON 及 ZIP 完整性通过。其他版本本轮未重测。

已知问题：新增 3D Viewport 标签缺中文词条，导致一项语言回归失败；Maya 上游键位含 objectshaderfx_copy、text.uncomment、clip.graph_select_all 三个无效操作符，尚未修复。长按、热盒及真实键盘交互未全量验收。本版供实测，不作为完整生产验收声明。
