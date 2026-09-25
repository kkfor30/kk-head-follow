<div align="center">

# KK Head Follow

**让网页里的角色，跟着鼠标转头。**

连续视频 → 方向图集 → 网页交互

[开始使用](#开始使用) · [制作流程](SKILL.md) · [效果视频](assets/readme/demo.mp4)

</div>

![鼠标指向左上或右上时，黄衣人物与小狗转头看向对应方向](assets/readme/head-follow-explainer-v1.png)

<p align="center">交互原理示意 · 实际效果见下方录屏</p>

https://github.com/user-attachments/assets/83d29722-03d3-45ca-bc54-2e1e39bb6875

<p align="center">6 秒实际网页演示 · <a href="assets/readme/demo.mp4">查看视频文件</a></p>

一个面向 AI 编程 `Agent` 的 Skill：从连续头部视频中识别方向、编译图集，并接入网页的鼠标跟随效果。适合个人主页、角色首屏和交互展示。

上方为维护者提供的实际效果录屏。它展示特定页面的体验，不是通用模板，也不代表任意输入素材都能一次成功。仓库不附带该页面的角色源图或生成原片。

## 它做什么

| 环节 | 能力 |
| --- | --- |
| 素材制作 | 复用已有视频；可选按首尾帧、动作参考或分段路线生成动作小样 |
| 提示词与试片 | 从同一动作规格组装提交文本，先检查原生动作与真实场景代表帧 |
| 图集编译 | 标定真实方向，裁切、可选补帧、处理背景与 Alpha |
| 网页接入 | 五个原生 ES modules，将鼠标方向映射到已有姿态帧 |
| 质量检查 | 检查接缝、方向、轮廓与来源；未通过检查时保留静态图 |

每个主体需要独立标定。眼神动作来自视频本身，没有独立眼球控制。

能否做成准确跟随，首先取决于素材有没有对应的真实方向动作。已有合适视频时可直接标定接入；只有静态图时，视频生成仍可能漏动作或改变身份。先用 `review_source_video.py` 检查母版，再投入图集和精修；“鼠标控制播放进度”不等于准确注视。具体判断见 [可行性与高效制作](references/feasibility.md)。

## 开始使用

### 一句话让 Agent 安装

在 Codex 或其他支持 Skill 的 Agent 中，复制并发送下面这句话：

> 请从 https://github.com/kkfor30/kk-head-follow 安装 kk-head-follow 技能，遵循本机已有的技能目录约定，并检查运行依赖。

### 手动安装与使用

将仓库放入支持 `SKILL.md` 的 `Agent` 技能目录，目录名保留为 `kk-head-follow`。例如 Codex 的用户技能目录为 `~/.codex/skills/`；也可以先克隆，再让 `Agent` 读取本仓库的 `SKILL.md`：

如果本机已配置统一的共享技能库，遵循该机器的安装管理入口和目录约定，不额外创建 Agent 私有副本。

```bash
git clone https://github.com/kkfor30/kk-head-follow.git
cd kk-head-follow
python -m pip install -r requirements.txt
```

运行环境：Python 3.10+、FFmpeg / FFprobe。配准与光流还需 `opencv-python-headless`；运行网页使用支持 ES modules 的现代浏览器，并通过 HTTP 提供页面。

对 `Agent` 说：

> 使用 $kk-head-follow，把我提供的连续头部视频接入现有网页，实现鼠标方向跟随。先检查视频是否覆盖完整方向，再交付可体验的候选并说明未通过的检查。

然后提供你的网页项目、底图、主体区域和输入视频。完整生产步骤见 [SKILL.md](SKILL.md)，浏览器接入见 [runtime.md](references/runtime.md)。

### 可选：生成动作视频

已有合适的视频可以跳过这一步。使用 ZenMux 时，通过隐藏输入配置自己的 API Key：

```bash
python scripts/zenmux_config.py set
```

Key 保存在用户配置目录，不写入仓库。新生成需要明确预算；5 秒用于低成本可行性小样；中性进入并完成整圈时，应在已授权预算内优先评估 8–10 秒，具体见[时长规划](references/generation-planning.md#按动作负荷选择时长)。参数与输入要求见 [生成指南](references/zenmux.md) 和 [示例配置](references/zenmux.example.json)。示例需要替换为真实素材与检查记录，不能直接作为即用 Demo。

现在可以从动作规格直接导出完整提示词，并由生成入口使用同一文本。完整环、中性进入、只补顶部与局部补段的配置见 [提示词配方](references/prompt-patterns.md)。它减少规格与提交内容脱节，仍需核对真实输入和成片。

## 从视频到交互

1. **检查动作**：识别视频真实覆盖的方向，标出缺失、停留与反向。
2. **检查融合再编译**：按 [场景路线](references/scene-routing.md) 处理深浅背景、复杂纹理与遮挡，先做 [少量帧真实场景合成](references/scene-samples.md)，再批量处理和打包。
3. **在页面体验**：先进入诊断预览，检查顺逆方向、接缝、缩放与遮挡。
4. **通过检查后启用**：质量记录绑定当前素材；素材变化后重新检查。

“生成完成”“页面能动”“工程检查通过”“用户验收通过”是不同状态。详细合同见 [素材与坐标](references/asset-contract.md)、[质量与修复](references/repair-and-review.md)。

## 当前边界

- **素材验收**：需要逐帧检查与实际页面验收，不承诺一次生成成功。
- **多角色分别制作**：一条视频请求只驱动一个角色，允许必要静态上下文；先验证单主体小样，再扩展其他角色。
- **方向环不等于二维精确注视**：眼睛动作已烘焙在视频中，同方向近远位置不改变幅度；表情、中性姿态与自然进出的处理见 [头部与眼神](references/gaze-and-rest.md)。
- **不包含自然回正系统**：鼠标进入中性区或移出时显示静态底图；自然进入、退出需要额外过渡素材。
- **方向缺失不能靠标签补齐**：完整方向环必须有对应动作证据。
- **复杂背景需要单独处理**：羽化不能消除内部色差、旧头轮廓或遮挡问题。

有限方向与动作相位可通过独立候选入口预览，并展示已知局限；候选预览不等于正式方向验收通过。生成前的路线选择与输入审查见 [生成规划](references/generation-planning.md)。

更多说明见 [版本范围](references/frozen-scope.md)。

## 开发与贡献

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s scripts -p "test_*.py"
node --test tests/*.test.mjs
```

测试验证工程行为，不代替视觉验收。提交问题时请说明复现步骤和环境；仅附可公开的素材，勿提交 Key、签名媒体链接、配置文件或私人项目记录。

[贡献说明](CONTRIBUTING.md) · [安全问题](SECURITY.md) · [更新记录](CHANGELOG.md)

## 许可

代码与文档采用 [MIT License](LICENSE)。演示媒体的使用说明见 [媒体说明](assets/readme/NOTICE.md)。
