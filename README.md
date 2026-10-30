# clawd 桌宠主题与补丁

给 [clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk)（Claude Code 桌宠，v1.4.0）做的角色主题、动画生成脚本和几个本地补丁。个人学习作品，**不商用**。

> Themes, animation build scripts and local patches for clawd-on-desk. Non-commercial fan project; not affiliated with Anthropic or the clawd-on-desk author.

## 里面有什么

| 目录 | 内容 |
|---|---|
| `qiansui/` | 千岁主题，可以直接用。素材转自 B 站/抖音作者 抖音@958792396 的桌宠（MIT，作者声明禁止商用） |
| `tools/build_qiansui_theme.py` | 从原桌宠的 PNG 帧生成千岁主题 |
| `tools/build_honami_theme.py` | 一之濑帆波主题的生成脚本：切图、抠绿幕、对齐脚底、逐帧拼动画（全部手绘中间帧硬切，不做渐变叠化）、输出 WebP 和 theme.json |
| `honami/codex-job/` | 让 Codex 画帆波各动作关键帧的提示词和运行脚本 |
| `honami/制作说明.md` | 帆波每个动作用了哪些帧、各停多久、为什么这样做 |
| `tools/clawd-patch/` | clawd 程序补丁（见下） |

**帆波的图没有放进来**：参考图、Codex 画的原画、生成好的主题都只留在本地。想做的话可以按 `honami/codex-job/` 里的提示词自己生成原画，放到 `honami/raw/`，再运行生成脚本。

## 安装主题

把主题文件夹（如 `qiansui/`）复制到 `%APPDATA%\clawd-on-desk\themes\`，然后在 clawd 设置 → Theme 里选择。

## clawd 补丁（可选）

补丁以“长度不变”的方式原地替换 `app.asar` 里的几个文件，只在 v1.4.0 上测过，clawd 自动更新后会失效。打之前先备份 `app.asar`。

- 额度圆环显示重置时间（`mkpatch.cjs`）
- 点击时从主题的 `files` 列表里随机挑一个动作，不连续重复（`mkpatch-hit.cjs`）
- 右键菜单“做动作”，读取主题 theme.json 的 `actionMenu`（`mkpatch-menu.cjs`）
- 睡眠改成“N 分钟没点她、Claude 也没动静”才睡，只有点她或 Claude 有动静才醒；闲着时每隔 `mouseIdleTimeout` 随机做一个动作（`mkpatch-sleep.cjs`）

用法：`node asartool.cjs extract <app.asar> <asar 内路径> xxx.orig.js` → `node mkpatch-xxx.cjs` 生成 `xxx.patched.js` → `node asartool.cjs patch <app.asar> <asar 内路径> xxx.patched.js`。

## 许可与版权

- 本仓库自己写的脚本、提示词和说明：MIT（见 `LICENSE`）。
- `tools/clawd-patch/`：修改自 rullerzhou-afk/clawd-on-desk，按其许可证 **AGPL-3.0-only** 发布（见该目录 `LICENSE`）。本仓库不包含 clawd 程序本体。
- `qiansui/`：素材版权归原作者，沿用原 MIT 许可和免责声明（见 `qiansui/LICENSE`），按作者要求不得商用。
- 一之濑帆波是《欢迎来到实力至上主义的教室》（衣笠彰梧 / トモセシュンサク / KADOKAWA）的角色，版权归原作方所有。本仓库只含同人用途的代码和文字提示词，不含任何角色图片。
- 禁止将本仓库内容用于任何商业用途。如有版权问题请提 issue，会尽快处理。
