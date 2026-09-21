# 情感反诈模拟器：存档与成就修改器

适用于 Steam 版《情感反诈模拟器 / RevengeOnGoldDiggers》（AppID `3350200`）的 Windows 图形化修改器。目前按游戏包版本 `1.2.0` 验证。

这是非官方、开源工具，与游戏开发商、发行商或 Valve 无关。使用前请自行备份存档。

## 下载

普通用户可从 GitHub Releases 下载 `RevengeOnGoldDiggersSaveEditor-v*-windows-x64.zip`，解压后运行 `RevengeOnGoldDiggersSaveEditor.exe`。程序为未签名的独立可执行文件，Windows 可能显示 SmartScreen 提示。

工具会自动寻找 Steam、游戏目录以及当前用户的 `archive.save` / `setting.save`。无需另装 Python 或 Node.js，但必须已经安装 Steam 版游戏。

## 功能

- 读取 39 项 Steam 成就状态，每次只选择一项解锁，并立即复读确认。
- 逐条修改角色档案与恋情档案的解锁、新内容标记。
- 展示 7 章共 632 个剧情节点及当前回收状态。
- 每次选择一个剧情节点，补齐抵达目标所需的最短前置路径；保留当前游玩位置和已有分支。
- 可用第一章至第七章的独立按钮，将指定章节的剧情节点及完整播放记录一次回收至 100%；不会顺带填满其他章节。
- 写入前同时备份两个存档；本地原子替换后，通过游戏自带 Steamworks 接口同步 Steam Cloud 并校验 SHA-256。
- 写入或 Cloud 校验失败时恢复原文件，并尽力恢复 Cloud 副本。

## 使用

1. 完全退出游戏。
2. 运行 Release 中的 `RevengeOnGoldDiggersSaveEditor.exe`；源码用户可双击 `启动情感反诈修改器.cmd`。
3. 在“Steam 成就”“档案 / 差分”或“剧情路线”页面选择一项操作。
4. 阅读确认框；确认后才会写入。
5. 首次建议只解锁一个无关紧要的节点，启动游戏检查路线图后再继续。

备份位于程序同目录的 `backups/时间戳/`，其中 `manifest.json` 记录源路径和两个文件的 SHA-256。请保留备份直到进游戏确认结果。

## 从源码运行与构建

需要 Windows 和 Python 3.11 或更高版本。源码运行本身仅使用 Python 标准库；Steam 操作复用已安装游戏的 Electron/Node 与 Steamworks 模块。

```powershell
python -m unittest -v test_public.py
python editor.py
```

生成与 Release 相同的 Windows 压缩包：

```powershell
.\build.ps1 -Version 1.0.0
```

构建脚本会创建被 Git 忽略的 `.venv`、`build`、`dist` 和 `artifacts` 目录，最终 ZIP 位于 `artifacts`。

`self_test.py` 是依赖本机真实 Steam 安装和 schema 的集成测试，不用于公共 CI。它只对临时存档测试写入流程。

## 隐私与数据边界

- 不包含网络请求、遥测或自动更新；只有明确操作时才调用本机 Steamworks 接口。
- 真实存档、备份、备份清单、解密资源、诊断脚本和构建目录均被 `.gitignore` 排除。
- 备份清单包含本机存档路径，请勿公开分享 `backups` 目录。
- 仓库只包含运行所需的剧情节点关系数据，不包含视频、图片、音频或完整游戏资源。

## 注意

- Steam Cloud 可能在游戏关闭或启动时同步存档；如果文件发生意外变化，请重新打开修改器，不要强行覆盖。
- 路线节点回收和 Steam 成就是两套状态；修改其中一项不会自动修改另一项。
- 剧情图谱来自已验证版本。游戏更新后结构可能改变，请先等待工具更新或自行核对。
- 当前路线算法补齐图上的最短前置路径，但不会伪造角色关系数值。少数带数值条件的隐藏节点仍需进游戏确认。
- 本工具不会提供无确认的一键全解锁，所有修改都按单项执行。

## 许可证

项目源码采用 MIT License。游戏名称、商标及游戏数据归其各自权利人所有。
