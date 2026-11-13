# Cloudflare Pages 免费镜像（可选）

站点目前部署在 GitHub Pages；从国内访问首字节较慢。Cloudflare Pages 免费、可自动部署，
配置后每次构建会同时发布到 `https://<项目名>.pages.dev`。

## 一次性配置（5 分钟）

1. 注册/登录 <https://dash.cloudflare.com/>
2. 左侧 **Workers & Pages → Create → Pages → Direct Upload**
   - 项目名例如 `football-data-desk`（记住它）
3. 创建 API Token：右上头像 → **My Profile → API Tokens → Create Token**
   - 模板选 **Edit Cloudflare Workers** 或自定义，权限至少包含：
     `Account → Cloudflare Pages → Edit`
4. 记下 **Account ID**（Cloudflare 控制台 URL 里 `dash.cloudflare.com/<account_id>` 那段）

## 在 GitHub 仓库加 3 个 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Name | 值 |
|---|---|
| `CF_API_TOKEN` | 第 3 步创建的 Token |
| `CF_ACCOUNT_ID` | 你的 Account ID |
| `CF_PAGES_PROJECT` | 第 2 步的项目名（如 `football-data-desk`） |

加完后下一次构建（最多 30 分钟）会自动执行 `wrangler pages deploy dist`。
之后打开 `https://<项目名>.pages.dev` 即可。

## 可选：自定义域名

Cloudflare Pages → 项目 → Custom domains 添加域名；绑定后我可以把站内 canonical/sitemap
的域名一起改成新域名。

## 说明

- 未配置密钥时该步骤自动跳过，GitHub Pages 不受影响
- 两个地址内容一致（同一份 dist），Service Worker 各自缓存
- Cloudflare 免费额度：每月 500 次构建、无限请求，足够当前使用
