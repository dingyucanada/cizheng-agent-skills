# 公开仓库与 GitHub Pages 部署

本仓库将代码、说明和公开教学材料放在一起；网站只发布 `site/`。Python 专业服务仍部署在本地 / Spark，不在 GitHub Pages 上运行。

## 发布内容

- `site/index.html`：作品价值、流程、架构、方法、资料、平台状态和参赛交付说明。
- `site/demo.html`：三套免上传教学案的完整浏览器体验。
- `site/assets/`：有明确公开许可的教学图片和本站静态资源。
- `site/data/`：项目编写的教学材料、来源及方法信息。

不要把私人案卷、数据库、模型权重、凭据文件、内部运行日志或用户培训 PDF 放到 `site/`。`.gitignore` 只是减少误加入，不能代替发布前检查；已经被 Git 跟踪的文件不会因为新增忽略规则自动消失。

## 本地预览

要求 Python 3.11 和 Node 22.13 或更高版本。网页运行不依赖 CDN 或外部前端包；开发验证使用锁定版本的 jsdom，DOM 检查与真实浏览器验收分别记录。

```bash
python scripts/build-public-site.py
npm ci --ignore-scripts
npm run test:web
python -m http.server 8820 --bind 127.0.0.1 --directory site
```

打开 `http://127.0.0.1:8820` 和 `http://127.0.0.1:8820/demo.html`。不要直接双击 HTML 文件；浏览器对 `file://` 的模块、资源加载与存储策略不同。公开体验使用 Web Crypto 核对文件，在部署的 HTTPS 或本机回环环境验证。

## Pages 工作流

`.github/workflows/pages.yml` 在默认 `main` 分支推送或手动触发时：

1. 取出源码，使用 Python 3.11 和 Node 22。
2. 执行公开网站构建与浏览器业务合同测试。
3. 用 `actions/configure-pages` 配置 Pages。
4. 用 `actions/upload-pages-artifact` **仅上传 `site/`**。
5. 独立部署任务使用 `pages: write` 与 `id-token: write`，部署到 `github-pages` 环境。

分支 CI 另运行固定依赖的完整 Python 工程测试、站点构建和 Node 合同测试。测试不需要真实模型或密钥；这些成绩证明工程协议，不证明专业模型质量。

在仓库 **Settings → Pages → Build and deployment** 将 Source 设为 **GitHub Actions**。工作流部署完成后，以实际 `github-pages` 环境返回的 URL 为准。项目站点通常位于 `https://<owner>.github.io/<repo>/`，资源采用相对路径，适合仓库子路径；自己的副本应更新主页和 README 中的仓库链接。

GitHub 官方部署合同见 [自定义 Pages 工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) 与 [创建 Pages 站点 API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-site)。Actions 的 Python / Node 配置分别遵循 [setup-python](https://github.com/actions/setup-python) 与 [setup-node](https://github.com/actions/setup-node) 官方接口。

## 发布后的验收

部署成功后实际检查首页、体验页、三套教学图片和方法资源均可打开。依次完成编辑、证据定位、补证、比较、复核备注和导出，确认页面刷新后的浏览器保存以及重置行为。用导出的清单核对文件，确认教学标识仍在且没有私人内容。

公开仓库应同时检查 README 相对链接、启动说明、固定依赖、七个 `SKILL.md`、许可证和 CI。若尚未录制作品视频、取得团队合影或完成模型实测，页面和比赛文档继续标为待完成，不能用空链接或假成绩补齐。

## 下午接入真实模型后的更新

保留静态教学入口。将可公开的真实 Spark 环境、模型版本、运行记录与专家个案验证补入文档；若展示回放，清楚标明其历史性质。密钥只在实际后端进程环境中配置，不能写进公开 HTML、JavaScript、GitHub 仓库或 Actions 输出。StepFun 只接明确批准的文字；公开站点不代理私人原图。
