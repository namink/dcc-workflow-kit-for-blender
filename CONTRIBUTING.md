# 参与维护

欢迎提交漏译、术语修正、兼容性问题或工作流切换回归。请附 Blender 版本、操作系统、工作流组合、界面语言、具体面板/命令和复现步骤。用户场景请先移除私人内容。

Max 译文位于 `src/dcc_workflow_kit/locales/max_zh_HANS.json`；Maya 译文位于 `src/dcc_workflow_kit/providers/maya/translations_zh_HANS.json`。只修改显示层，不翻译操作符 ID、RNA 标识、脚本、文件路径或用户名称。译文中的变量和格式说明必须完整保留。

维护期 `tools/import_sources.py`、`tools/localize_max.py`、`tools/mark_max_messages.py` 和 `tools/complete_maya_display.py` 是历史转换工具，不是可覆盖运行的更新器。修改当前源码后执行 `python tools/build.py` 即可离线构建安装包。

测试会切换界面、创建数据并关闭测试进程，只能在隔离的 Blender 配置和工厂场景中运行。禁止在正在工作的用户场景中运行测试。

保留原作者、本地化作者、SPDX 标识及资产声明；提交代码沿用项目 GPL-3.0-or-later 许可。
