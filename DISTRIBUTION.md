# Framelet 分发说明

## GitHub 文件怎么放

仓库的 **Code** 页面放源码、运行资源和文档。**Releases** 页面放打包好的 Windows 下载文件。

### 提交到仓库

按下列清单提交文件，并保留 `docs/media/`、`lucide/` 和 `tests/` 的目录结构。

| 用途 | 文件 |
| --- | --- |
| 文档和提交规则 | `README.md`、`README.en.md`、`DISTRIBUTION.md`、`.gitignore` |
| README 图片和动图 | `docs/media/framelet-settings.png`、`docs/media/framelet-workflow.gif` |
| 源码与测试 | 根目录的所有 `.py` 文件、`tests/` 中的 `.py` 文件 |
| 依赖、启动和打包 | `requirements.txt`、`requirements-build.txt`、`Framelet.bat`、`build-release.bat`、`version_info.txt` |
| 运行资源 | `Framelet.png`、`support-qr.png`、整个 `lucide/`，包括其中的 `LICENSE` |

`support-qr.png` 和 `widgets.py` 中的作者邮箱会出现在应用的支持窗口，也会随发布包分发。公开仓库和下载包前，确认这两项是你希望公开的内容。

项目根目录目前还没有 Framelet 自己的许可证。`lucide/LICENSE` 适用于图标素材。如果希望允许别人修改和再分发 Framelet，先选定项目许可证，再把 `LICENSE` 放到仓库根目录。参见 [GitHub 的仓库许可证说明](https://docs.github.com/zh/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

### 留在本地

| 文件 | 用途 |
| --- | --- |
| `__pycache__/`、`*.pyc`、`framelet.log`、`test-artifacts/` | Python 缓存、运行日志和测试生成的截图 |
| `build/`、`dist/`、`Framelet.ico`、`Framelet.spec` | 打包过程生成的文件。脚本会从 `Framelet.png` 生成 ICO，并按命令参数生成 spec。 |
| `启动录屏.bat`、`容器 201.png` | 旧启动入口和图标原图副本。仓库使用 `Framelet.bat` 和 `Framelet.png`。 |
| `PRODUCT.md` | 本地产品设计笔记。决定公开时可从 `.gitignore` 移除这条规则。 |

用 Git 提交时，`.gitignore` 会排除未跟踪的本地文件，可以用 `git add --dry-run .` 预览清单。在 GitHub 网页点 **Add file → Upload files** 时，按上面的仓库清单手动选择文件。参见 [GitHub 的文件上传步骤](https://docs.github.com/zh/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)。

### 添加到 GitHub Release

构建完成后，从 `dist/` 中选这两个文件作为 Release 附件。

```text
dist\Framelet-3.3-Windows-x64.zip
dist\Framelet-3.3-Windows-x64.zip.sha256
```

1. 先把这一版源码提交到 GitHub。
2. 在仓库打开 **Releases → Draft a new release**，创建对应版本标签，例如 `v3.3.0`，目标选到这版代码所在的分支。
3. 写版本主要改动与运行方式，把 ZIP 和 `.sha256` 拖到附件区。检查齐全后点击 **Publish release**。参见 [GitHub 的 Release 发布步骤](https://docs.github.com/zh/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

GitHub 会基于该标签自动附上 `Source code (zip)` 和 `Source code (tar.gz)`。Windows 用户下载 `Framelet-3.3-Windows-x64.zip`，完整解压后双击 `Framelet\Framelet.exe`。ZIP 自带运行环境和必需的 `_internal` 目录。参见 [GitHub 的 Release 附件说明](https://docs.github.com/zh/repositories/releasing-projects-on-github/about-releases)。

## 构建 Windows 发布包

准备 64 位 Windows 和 64 位 Python 3.12，在项目目录执行以下命令。

```powershell
py -3.12 -m pip install -r requirements.txt -r requirements-build.txt
.\build-release.bat
```

脚本会从 `Framelet.png` 生成 `Framelet.ico`，再用 PyInstaller 的目录模式构建，关闭 UPX，并写入产品名和版本信息。最后在 `dist/` 下输出 ZIP 和 SHA-256 校验文件。

## 为什么旧版容易报毒

旧版是约 78 MB 的未签名 PyInstaller 单文件程序。单文件模式会在启动时把 Python、Qt、FFmpeg 等组件解压到临时目录；Framelet 同时需要读取全局按键状态、捕获屏幕和写入剪贴板。这些都是录屏工具的正常功能，但组合起来容易触发杀毒软件的启发式规则。

目录版能去掉“运行时自解压”这一项可疑特征，但不能承诺所有安全软件都不再告警。不要通过关闭 Defender、让用户添加排除项或修改代码来规避检测。

## 分发前检查

- 公开分发 Windows ZIP 前，按实际打包的版本核对第三方组件的再分发条款。当前环境的 FFmpeg 启用了 GPL 组件，打包脚本也会收集 FFmpeg。发布时核对 FFmpeg 的许可证文本与对应源码获取方式，同时检查 PySide6 / Qt 的许可证和随包说明。参见 [FFmpeg 许可证说明](https://ffmpeg.org/legal.html)和 [Qt for Python 许可证说明](https://doc.qt.io/qtforpython-6/licenses.html)。
- 在一台没有 Python 的 Windows 设备上测试一次区域选择、重复快捷键录制、GIF/MP4 导出和文件复制。
- 用 `.sha256` 文件核对 ZIP 是否在传输中被篡改。
- 未签名程序仍可能触发 Defender、SmartScreen 或第三方杀毒软件。正式发布应使用受信任 CA 签发的 RSA 代码签名证书，对 `Framelet.exe` 签名并添加 SHA-256 时间戳。
- 如果 Microsoft Defender 给出明确病毒名称，而你确认代码和构建机干净，可在 Microsoft Security Intelligence 的“Software developer”入口提交误报复核；提交时附上检测名称、SHA-256、产品功能和复现步骤。
- 不要只发送项目源码或 `Framelet.bat`；它们依赖 Python 环境。
- 这是无安装版。设置窗口的"开机自动启动"默认勾选，会写入当前用户的 Run 注册表项；取消勾选即可移除，也可手动把 EXE 的快捷方式放入 Windows 的 `shell:startup` 文件夹。

剪贴板临时文件位于系统临时目录的 `Framelet-clipboard` 文件夹；系统清理临时文件后会失效，长期保留请导出或粘贴另存。
