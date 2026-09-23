---
name: kk-head-follow
description: 实验版：将连续头部视频制作成网页鼠标方向随动，支持可选素材生成、图集编译和质量检查；自然回正与复杂遮挡需单独验证。
---

# KK Head Follow

冻结版本：`0.1.0-experimental.1`（2026-09-23）。开始前读 [版本范围与示例](references/frozen-scope.md)。冻结的是可追溯的制作工具链和候选交付流程，不是任意图片一次生成成功的承诺。

让头部与眼神在前方视线范围内，沿屏幕方向连续绕行并跟随鼠标。使用视频中真实存在的姿态；保留输入身份、表情、嘴部状态、身体和网页布局。一圈指上→右→下→左→上的连续方向环，经过所有中间方向。眼睛动作烘焙在视频中，不承诺独立眼球控制或距离决定转头幅度。

## 首轮目标与迭代

先读 [iteration-delivery.md](references/iteration-delivery.md)。默认一次 5 秒试片；先核验母版关键动作，再有限程序处理，尽早在实际网页交付带明确状态的候选。完整方向候选可在诊断页鼠标体验；部分方向不得冒充整圈。正式 ready 与候选预览分开。用户后续反馈驱动定点修复，不自动追加付费生成；同一任务所有生成沿用一个累计预算。

## 输入与合成

已有网页或已验收素材时优先复用。先读 [subject-production.md](references/subject-production.md) 确定交付场景：新建首屏默认按“构图参考 → 无角色背景与透明角色 → 目标首屏静态合成 → 单主体 5 秒动作小样 → 原场景接入”推进。独立纯色测试只能核验动作，不能替代用户要求的复杂首屏。静态与交互使用同一套分层素材、位置和缩放；用户要求保留完整旧照片时属于进阶局部替换，不擅自重设计。生成脚本的 production 阶段绑定实际 pilot 来源与检查结果。每个主体独立标定，Skill 不依赖私人路径、角色或历史会话。

读 [background-delivery.md](references/background-delivery.md) 选择固定场景补丁，或逐帧 Alpha 与去除旧头的干净底图。视频背景不自动等于原图背景；羽化不能修复矩形内部的色差或纹理变化。输入保留完整头颈和运动余量，生成输入与最终绘制区分开并保持比例。

依赖：Python 3.10+、NumPy、Pillow、FFmpeg/FFprobe；配准和光流额外需要 opencv-python-headless。网页用 HTTP 提供 ES modules。脚本使用 Skill 的绝对路径，下文命令以该目录为工作目录，项目路径显式指定。

## 制作、修复与检查

0. 新建分层首屏先按 [layered-scene.md](references/layered-scene.md) 合成静态图与各主体 cleanPlate，记录角色、阴影、位置和尺寸。可用 `compose_layered_scene.py` 避免手工重复对齐。先检查实际首屏构图、落地感和邻近遮挡；已有用户验收可直接复用。检查通过只证明静态融合；同一角色的抬头参考若重新生成，也需重新核对外观和比例。
1. 记录底图、ROI、视频与工作坐标、眼睛位置，读 [asset-contract.md](references/asset-contract.md)。运行 `segment_head_motion.py --video ... --crop x y w h --output ... --keep-samples`。crop 是视频坐标。查看源样本，标出进入/退出、停留、反向和缺失方向；不按时长均分，不把正视标成上看。像素运动量不判断动作语义。
2. 读 [motion-quality.md](references/motion-quality.md) 与 [repair-and-review.md](references/repair-and-review.md)。先确认母版动作可用，再裁段、重新标定和处理采样密度；完整连续动作可用 `densify_head_video.py` 生成 2× 候选及逐帧来源，接缝桥接是另一种操作。大段缺失不得改标签掩盖。不因背景问题自动重生成。
3. `compile_head_atlas.py spec.json --root PROJECT` 编译候选；`validate_head_manifest.py manifest.json --root PROJECT` 校验结构、源文件和坐标。多主体用 `--compare` 核对共同底图和绘制区。编译成功不等于可正式启用方向环。
4. 运行 `inspect_atlas_seams.py manifest.json --output seam-review` 与 `review_head_atlas.py manifest.json --root PROJECT --output review`，输出所有帧、跨源与闭环接点、合成段和双向整圈证据。Agent 主动逐页查看发丝、耳朵、眼镜、颈根、旧头轮廓和背景；不把首次找错交给用户。
5. `audit_head_atlas.py manifest.json --root PROJECT --write-review-template review/observations.json` 建立绑定当前像素的观察表。按实际证据填写方向、眼神、接缝趋势、背景、轮廓、合成帧及交互检查；未检查保持 unknown / unreviewed。静态背景遮罩避开旧头和新头完整运动并集。模板不是合格证据。
6. 失败项按 [repair-and-review.md](references/repair-and-review.md) 分流；需要前景分离时先制作和核对逐帧遮罩。用 `repair_head_atlas.py` 输出独立候选，重跑结构、证据与质量检查，比较改善和新增问题。所有合成帧保留来源；降低像素差不代表残影消失。修复失败保留原件和证据，不覆盖素材，不无限换算法或付费重试。没有缺陷则跳过修复。
7. 复制 assets 下四个 `.mjs` 模块，按 [runtime.md](references/runtime.md) 在使用目标首屏背景与布局的诊断页显式启用 `diagnosticPreview:true`，检查完整顺/逆时针、两向慢速跨顶部、回正、缩放、脚底漂移与前后遮挡。交互帧与静态角色在同一坐标系下切换，不能临时把新头接回另一张图的旧身体。受环境或用户要求限制不能浏览器检查时记录未测试，继续可执行的离线检查，不填写交互通过。
8. 全部检查满足后，`audit_head_atlas.py manifest.json --root PROJECT --review review/observations.json --approve` 写入工程检查记录，再用 `validate_head_manifest.py manifest.json --root PROJECT --require-ready` 验证。正式页面不传诊断开关；未检查或报告/底图/图集变化时运行时保留静态图。用户仍做最终体验验收。

首轮必须按 iteration-delivery.md 交付实际可完成的候选或合成诊断；不因尚未达到正式 ready 而省略可体验版本。说明未完成项与原因。“生成完成”“网页能动”“工程检查通过”“用户验收通过”分开报告。

## 生成入口

读 [zenmux.md](references/zenmux.md) 和 [prompt-patterns.md](references/prompt-patterns.md)。默认 5 秒/768p 小样；预算同时限制秒数、模型和次数。实际请求必须有 motionPlan、显式时长、真实首尾约束与本地输入检查记录；`--dry-run` 在占用预算前核对。中性首图进入一圈与同一抬头首尾闭环是不同方案，不能混用。

通过 `zenmux_config.py set` 隐藏输入 Key，不写入项目。付费按已有授权和显式 `--budget` 执行，不自动重试；查询旧任务用 `--job-id`。请求发出前占用一次，超时不自动退还，不换预算绕过上限。输出保存实际提示词和脱敏请求摘要。新提示词仍待新素材实测，不能保证一次成功。

## 修改 Skill 后验证

运行 `python -m unittest discover -s scripts -p "test_*.py"` 和 `node --test tests/*.test.mjs`。配准/光流测试需安装可选依赖，不把 skip 当通过。再用保留的失败素材检查错误是否被拒绝、修复候选是否保留来源与坐标、文档示例是否可执行。代码测试不等于视频生成成功率或视觉验收。能力边界见 [architecture.md](references/architecture.md)。
