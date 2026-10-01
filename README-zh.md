# ComfyUI Image Browser

适用于 ComfyUI 的图片浏览扩展，由 [Hanaikada 花筏](https://github.com/licyk/Hanaikada) 驱动。

在 ComfyUI 顶部点击 **Lucide Images** 图片图标（提示文字“图片浏览器”），直接打开 Hanaikada，浏览、搜索、标记、对比和管理 ComfyUI 生成的图片。提示词、种子、模型和采样器等参数从 ComfyUI 写入图片的工作流中读取。

- 默认打开 ComfyUI 的 `output` 目录，`input` 目录作为第二个根目录；两者都遵循 `--output-directory`、`--input-directory` 和 `--base-directory`。
- 浏览页默认打开“全部文件夹”：并列显示 ComfyUI 的 `output` 和 `input`。扩展固定开启它，Hanaikada 设置中的开关不会生效；可用 `COMFYUI_IMAGE_BROWSER_COMBINED_VIEW=0` 关闭，此时浏览页默认打开 `output`。
- 任务完成后新图片立即出现：扩展会让 Hanaikada 立即索引 ComfyUI 刚写入的文件夹，不必等待目录轮询。
- 在 `input` 目录中上传、复制、移动、重命名或删除文件后，**Load Image** 等节点的图片列表会自动刷新。
- **打开工作流**（图片菜单或查看器的“发送到”按钮）会在新的工作流标签页中打开 ComfyUI 的 PNG、WebP、AVIF 中保存的工作流，或 WebUI PNG 中的参数；当前工作流保持不变。
- **发送到加载图像节点**会把图片放进选中的 **Load Image** 节点（没有选中时新建一个）：`output` 中的文件会复制上传到 `input`，已在 `input` 中的文件直接选用。
- 关闭窗口后保留当前目录、搜索和查看器状态，再次打开即可继续。
- 首次打开时启动服务，日常启动 ComfyUI 不扫描图片。
- Python 安装和目录结构参考 [ComfyUI-HakuImg](https://github.com/licyk/ComfyUI-HakuImg)，无需 Node.js 或前端构建。

## 安装

在 ComfyUI 目录下使用 Git 克隆本扩展：

```bash
git clone https://github.com/licyk/comfyui-image-browser.git custom_nodes/comfyui-image-browser
```

重启 ComfyUI，刷新浏览器。扩展的 `prestartup_script.py` 会检查依赖，使用 **ComfyUI 当前运行的 Python** 安装缺失或版本不兼容的依赖。

## 使用与目录

顶部按钮或 Tools 菜单中的 **Open Image Browser** 打开窗口，默认进入 Hanaikada 浏览页面的“全部文件夹”，支持最大化、关闭和重试。浏览器内没有聚焦任何控件时按 Esc 关闭窗口；浏览器内的 Esc 优先用于取消选择或关闭菜单、抽屉和查看器。

新版前端使用操作栏按钮，旧版前端使用旧顶部菜单。窗口标题栏提供 **在新标签页打开**，即使内嵌窗口启动失败也可以使用：新标签页会在自己的来源下独立启动 Hanaikada，再进入浏览页面。

根目录由 ComfyUI 决定，在 Hanaikada 中不可新增、修改或删除，因此浏览器无法访问 ComfyUI 图片目录以外的路径。设置 `COMFYUI_IMAGE_BROWSER_INCLUDE_TEMP=1` 可额外浏览 `temp` 目录（预览图），ComfyUI 每次启动都会清空该目录，因此只浏览不索引。修改 ComfyUI 目录参数后需重启。

索引、缩略图和设置位于：

```text
<ComfyUI user 目录>/__image_browser/
```

这会遵循 ComfyUI 的自定义 user 目录设置，不会写入扩展目录，也不会占用独立 Hanaikada 的数据目录。依赖自动安装失败时可查看启动日志排查原因；Hanaikada 启动失败时窗口会显示 HTTP 状态和请求路径并允许重试。

## 远程访问

所有浏览器请求都通过 ComfyUI 同源的 `/image-browser/` 路径转发。内部 Hanaikada 只监听随机的本机回环端口，并使用仅后端持有的令牌认证。代理支持流式 HTTP（上传、zip 下载、缩略图）、WebSocket 和 Socket.IO 轮询，无需额外开放端口。

反向代理需要转发整个 ComfyUI 部署路径，包括 WebSocket 升级。代理终止 TLS 或改写 Host 后，带有 `Sec-Fetch-Site: same-origin` 的合法浏览器来源仍会被接受；跨站和不透明来源（`Origin: null`）的请求会被拒绝。ComfyUI 被嵌入沙箱或其他网站时，请使用“在新标签页打开”。

窗口以同源 iframe 嵌入 `/image-browser/`。代理响应附带 `Content-Security-Policy: frame-ancestors 'self'`，因此反向代理或 CDN 添加的 `X-Frame-Options: DENY` 会被浏览器忽略。若代理自身的 CSP 设置了更严格的 `frame-ancestors`，或删除、替换后端的 CSP 头，嵌入仍会被阻止，窗口会提示原因。请为 ComfyUI 主机允许 `frame-ancestors 'self'`，或使用“在新标签页打开”。

若代理会移除浏览器来源信息，请设置浏览器的外部地址（包含代理前缀）：

```bash
export COMFYUI_IMAGE_BROWSER_PUBLIC_BASE_URL=https://example.com/comfy/image-browser
```

图片浏览器继承 ComfyUI 的访问权限：能使用 ComfyUI 的人即可查看、移动和删除其中的图片，ComfyUI 的用户 ID 不提供单独授权。现有的部署认证需要同时覆盖 HTTP 和 WebSocket 路径。与独立运行的 Hanaikada 相同，“在文件管理器中打开”只对服务器本机上的浏览器可用。

“全部文件夹”固定开启；设置 `COMFYUI_IMAGE_BROWSER_COMBINED_VIEW=0` 可固定关闭。

设置 `COMFYUI_IMAGE_BROWSER_AUTO_INSTALL=0` 可手动管理依赖。安装日志可通过 `COMFYUI_IMAGE_BROWSER_LOGGER_NAME`、`COMFYUI_IMAGE_BROWSER_LOGGER_LEVEL`（默认 `20`）和 `COMFYUI_IMAGE_BROWSER_LOGGER_COLOR`（`0` 关闭颜色）配置。

## 开发

```bash
python -m playwright install chromium
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m ty check --python /path/to/comfy/python
node --check js/image_browser.js
node --test tests/*.mjs
```

类型检查默认 ComfyUI 位于 `../ComfyUI`，否则请传入 `--extra-search-path /path/to/ComfyUI`。浏览器测试可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定 Chromium。

测试使用已发布的 Hanaikada、临时 ComfyUI 目录和带有 ComfyUI 元数据的图片。Chromium 测试在一个实现 ComfyUI 公共扩展注册接口的小型宿主页面中运行真实的 Hanaikada 界面，不能替代完整的 ComfyUI 前端或 GPU 工作流测试。

使用 [GPL-3.0-only](LICENSE) 许可。
