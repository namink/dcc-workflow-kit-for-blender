# 0.1.7 空格切换修复（2026-11-25）

- 修复 Blender 4.2.9 Maya 模式中短按空格进入四视图后无法返回的问题。
- 对不支持坐标合并区域的 Blender，使用原生区域最大化，在四视图和当前面板之间切换。
- 单视图时周围面板暂时隐藏，再按空格恢复四视图及周围面板。
- 独立 Blender 4.2.9 GUI 测试通过四轮往返；测试调用空格绑定的操作符，未模拟物理按键。
- 原有模式切换和全部工具未重新完整回归。

以下为 0.1.6 基线记录，其测试结果不代表本次重新运行。

# Blender 4.2.9 兼容维护版 0.1.6

2026-11-23。修改副本位于当前项目，原 C:/Codex/Blender/dcc-workflow-kit-retry 未覆盖。

## 已完成

- 安装版本下限调整为 4.2.9；加入从官方 4.2.9 生成的 Industry Compatible 快捷键数据。
- 过滤当前版本不存在的非模态快捷键操作符及属性。
- 将 Max 两个 5.0 工作区转换为旧格式；Maya 模板保留面板标识，4.2 通过 Screen 自定义属性保存缺失的 Properties 标签标志。
- UV Unfold 在缺少 Minimum Stretch 时使用 Angle Based；雕刻及权重工具使用 4.2 的原生笔刷系统。
- 保留 Max/Maya 中文目录，补译“3D 视图”；帮助菜单跟随运行中的 Blender 文档版本。

## 实测

Windows 官方 Blender 4.2.9 LTS：生命周期 9/9、数据与保存重开 6/6、汉化 5/5、选取的上游菜单回归 12/12、GUI 15/15，共 47/47；安装包身份、工具架无损导入、设置路径及清理 4/4，总计 51/51。附加兼容检查覆盖面板角色、原生键位、帮助链接、循环边绑定、雕刻 Draw、UV Unfold 和 2690 个注册快捷键操作符。

Blender 4.5.12 LTS 另通过生命周期 9/9 和 GUI 15/15。

测试使用独立用户配置和工厂场景。GUI 截图及报告见 test-results/gui-4.2.9-LTS。自动 GUI 检查覆盖切换和多窗口，不能替代全部工具的鼠标/键盘实际交互验收。

## 限制

- 上游新版 Maya 0.21.0 与 MaxFlow 0.8.5 均要求 Blender >=5.0；本分支保留 Maya 0.6.2 / Max 0.6.8 基线，选择性回移兼容修复，**没有全量合入最新版功能**。
- Blender 4.2 缺少新版笔刷资产系统；权重笔刷资产浏览入口会说明需使用原生笔刷设置。部分新版雕刻笔刷没有旧版对应项，会提示不可用。
- UV Unfold 的 Angle Based 结果与新版 Minimum Stretch 不完全一致。
- 4.2 无 Point Cloud 原生键位及笔刷资产弹窗，日志会记录 9 条上游键位补丁差异；不会阻止切换。
- 自定义拆分/合并 Maya Properties 面板后的角色保持、所有绑定/动画/渲染工具及全部操作尚未逐项回归。Rigify 工具需要单独启用 Rigify。
- 同一进程不能同时使用 Max 和 Maya 两套交互；不可同时启用独立原插件；不提供 .max/.ma/.mb 原生读写。

## 上游核对

- Maya：https://github.com/5hyuns/maya-workflow-kit-for-blender/blob/master/src/allset/blender_manifest.toml ，本次读取版本 0.21.0，最低 5.0，重点支持 5.2/5.3。回移 compat.docs_url 并接入两个菜单映射，保留 4.x 文档。
- Max：https://github.com/neom315/blender-max/blob/main/blender_max-0.8.5.zip ，发布清单版本 0.8.5，最低 5.0。回移循环边/环操作符的能力检测。
- 已记录原始基线于 MAYA_UPSTREAM.json、UPSTREAM_HASHES.json，不将选择性回移伪记为完整升级。

安装 dist/dcc-workflow-kit-0.1.6.zip；Blender 选择简体中文并开启界面翻译。
