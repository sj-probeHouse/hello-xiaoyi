# 你好，小译 / HELLO XIAOYI

Windows 全局英译中与英文朗读助手，面向计算机、AI、电子工程文献阅读。

## 开始使用

1. 解压便携 ZIP，保留整个 `HelloXiaoyi` 文件夹，运行 `HelloXiaoyi.exe`。
2. 在设置中选择 DeepSeek 或 MiMo，填写 API Key，点击「测试翻译连接」，成功后「保存设置」。也可使用自定义 HTTPS 兼容接口。
3. 在网页、带文本层的 PDF 或 Zotero 中选中英文，**按住 Ctrl，在 600 毫秒内按下、松开、再按一次 C**。
4. 鼠标旁显示翻译卡片。点击「朗读原文」播放英文；支持停止、复制译文、重试、固定卡片与 Esc 关闭。
5. 托盘图标可打开设置；右键可暂停全局取词或退出。关闭设置窗口后程序继续运行。

更新版本时，先从托盘退出小译，再将新版完整文件夹放到原使用位置，或更新快捷方式指向新版。仅在其他目录解压新版不会更新旧程序；旧实例仍运行时，打开新版也只会唤起旧实例的设置。API Key 和用户设置保存在用户目录及凭据管理器中，替换程序无需重填。

单次 Ctrl+C 仍然正常复制。程序不主动恢复旧剪贴板，也不会覆盖此次正常复制结果；点击「复制译文」才写入译文。没有新复制内容时不会翻译旧剪贴板。

首次自然语音无需 API Key，但需要联网。可在设置中选择英美音色、语速，或改用 Windows 系统英文语音。朗读失败不会自动发送到其他语音服务。

朗读期间，同一段文字的重复请求不会从头重播；卡片显示播放进度及完成／中断状态。卡片被动收起后朗读继续，可按 Esc 或在托盘选择「停止朗读」。点击卡片关闭、暂停取词或激活新选区会停止当前朗读。

## 配置

| 服务 | Base URL | 默认模型 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash` |
| MiMo | `https://api.xiaomimimo.com/v1` | `mimo-v2.6-flash` |
| 自定义 | 你配置的 HTTPS 基础地址 | 手工填写 |

接口会追加 `/chat/completions`，基础地址不要填写完整接口路径。模型名称可自行修改。MiMo Token Plan 的专用地址与普通按量计费地址可能不同，使用控制台对应的 Base URL 与 Key。

程序按普通快速模式调用预设服务，关闭深度思考。首次测试会发送单词 `attention`，可能产生少量费用；不会自动调用其他付费服务。具体模型可用性与计费以服务商为准。

API Key 仅存 Windows 凭据管理器；普通设置及音频缓存位于 `%LOCALAPPDATA%\HelloXiaoyi`。翻译结果只做内存缓存，不保存论文历史。在线翻译发送所选文字及领域提示；在线朗读发送所朗读文字。程序不监听或上传持续变化的剪贴板内容，不读取整篇文档。

开机启动默认关闭，开启后注册当前程序的绝对路径；移动便携文件夹后，请重新关闭再开启该选项。

## 支持范围

- Windows 11 x64，普通权限的可复制文字应用；每次最多 8000 字符。
- 单词提供简短词性、常用义和可能的学术义；句段忠实翻译，保留变量、公式与引用。
- PDF 换行可整理；可见连字符保持原样，避免把 `state-of-the-art` 等复合词误合并。模型会结合句段理解断词。
- 扫描 PDF、截图、禁止复制内容、管理员权限窗口不属于首版支持范围。
- 各阅读器兼容性及真实翻译质量须按 [验收记录](docs/TESTING.md) 实测；语音在线服务没有可用性保证。

## 从源码运行

在项目目录使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\pythonw.exe main.py
```

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=xiaoyi --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/build.py
```

便携包输出到 `dist/HelloXiaoyi-0.1.1-windows-x64.zip`，程序目录为 `dist/0.1.1/HelloXiaoyi`。构建会包含独立 Python、Qt 运行时及音频组件，无需用户安装 Python。Windows CI 同样执行测试与打包。

项目代码按取词规则、原生接口、网络服务和 Qt 界面组织，无后台服务器与 Agent 依赖。后续功能见 [路线图](docs/ROADMAP.md)。第三方组件许可见 [声明](THIRD_PARTY_NOTICES.md)。
