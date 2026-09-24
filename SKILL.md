---
name: kk-head-follow
description: 制作人物、动物或角色的网页头部与视线跟随；按目标选择首尾帧、动作参考或分段生成，提供真实方向与实验候选接入。自然回正需独立素材。
---

# KK Head Follow

版本：`0.2.0-experimental.1`（2026-09-24）。开始前读 [版本范围与示例](references/frozen-scope.md)。本次生成控制与候选接入经离线工程验证；新路线和提示词尚无跨素材生成成功率证据。

让头部与眼神在前方视线范围内跟随鼠标，保留原身份、表情、嘴部状态、身体和布局。按实际主体与目标确定幅度、可见性和允许侧倾，不把某个人物或动物的姿态写成通用标准。正式方向环指上→右→下→左→上的连续姿态，经过中间方向；使用真实存在的动作，不靠假锚点填缺口。眼睛动作烘焙在视频中，不承诺独立眼球或按距离改变幅度。

## 首轮目标与迭代

先读 [iteration-delivery.md](references/iteration-delivery.md)。默认一次5秒/768p小样，按动作与已有预算调整，不把5秒当最佳时长。先核验母版，再有限程序处理，在真实页面尽早交付有缺陷说明的候选。完整方向、有限方向、实验相位与播放诊断分开，实验候选不写 ready。已有交互实现请求包含独立候选入口的接入，不需用户再说“硬接”；默认首页启用遵循用户要求。所有生成沿用累计预算，不自动追加付费重试。

## 生成前控制

需要新素材时先读 [generation-planning.md](references/generation-planning.md)，根据要求选择首尾帧、动作参考或必要的分段。首尾控制端点，示范帮助约束动作，提示词描述变化，固定背景与鼠标时序交给程序。相同首尾不约束整条路线，不能靠增加禁止句保证方向完整。

在 motionPlan.requirements 记录可观察目标、实际控制来源和核对方法，据同一规格写 prompt 并验收。先检查输入身份、姿态、幅度、特征可见性、构图、固定项与图文一致性；失败帧仅因方向正确也不能直接作为新身份基准。使用请求绑定的观察模板，Agent 填写实际结论，unknown 不伪装通过。模板是记录工具，不要求用户重复批准。

## 输入与合成

已有网页或已验收素材时优先复用。先读 [subject-production.md](references/subject-production.md) 确定交付场景：新建首屏默认按“构图参考 → 无角色背景与透明角色 → 目标首屏静态合成 → 单主体动作小样 → 原场景接入”推进。独立纯色测试只能核验动作，不能替代用户要求的复杂首屏。静态与交互使用同一套分层素材、位置和缩放；用户要求保留完整旧照片时属于进阶局部替换，不擅自重设计。生成脚本的 production 阶段绑定实际 pilot 来源与检查结果。每个主体独立标定，Skill 不依赖私人路径、角色或历史会话。

读 [background-delivery.md](references/background-delivery.md) 选择固定场景补丁，或逐帧 Alpha 与去除旧头的干净底图。视频背景不自动等于原图背景；羽化不能修复矩形内部的色差或纹理变化。输入保留完整头颈和运动余量，生成输入与最终绘制区分开并保持比例。

依赖：Python 3.10+、NumPy、Pillow、FFmpeg/FFprobe；配准和光流额外需要 opencv-python-headless。网页用 HTTP 提供 ES modules。脚本使用 Skill 的绝对路径，下文命令以该目录为工作目录，项目路径显式指定。

## 制作、修复与检查

0. 新建分层首屏先按 [layered-scene.md](references/layered-scene.md) 合成静态图与各主体 cleanPlate，记录角色、阴影、位置和尺寸。可用 `compose_layered_scene.py` 避免手工重复对齐。先检查实际首屏构图、落地感和邻近遮挡；已有用户验收可直接复用。检查通过只证明静态融合；同一角色的抬头参考若重新生成，也需重新核对外观和比例。
1. 记录底图、ROI、视频与工作坐标、眼睛位置，读 [asset-contract.md](references/asset-contract.md)。运行 `segment_head_motion.py --video ... --crop x y w h --output ... --keep-samples`。crop 是视频坐标。查看源样本，标出进入/退出、停留、反向和缺失方向；不按时长均分，不把正视标成上看。像素运动量不判断动作语义。
2. 读 [motion-quality.md](references/motion-quality.md) 与 [repair-and-review.md](references/repair-and-review.md)。先确认母版动作可用，再裁段、重新标定和处理采样密度；完整连续动作可用 `densify_head_video.py` 生成 2× 候选及逐帧来源，接缝桥接是另一种操作。大段缺失不得改标签掩盖。不因背景问题自动重生成。
3. `compile_head_atlas.py spec.json --root PROJECT` 编译候选；`validate_head_manifest.py manifest.json --root PROJECT` 校验结构、源文件和坐标。方向不足但可体验时按 [runtime.md](references/runtime.md) 的 preview 编译，不编造八锚点。多主体用 `--compare` 核对共同底图和绘制区。编译成功不等于正式方向通过。
4. 运行 `inspect_atlas_seams.py manifest.json --output seam-review` 与 `review_head_atlas.py manifest.json --root PROJECT --output review`，输出所有帧、跨源与闭环接点、合成段和双向证据；arc 检查区间内往返，不要求其端点闭环。Agent 主动逐页查看发丝、耳朵、眼镜、颈根、旧头轮廓和背景；不把首次找错交给用户。
5. 正式方向候选用 `audit_head_atlas.py manifest.json --root PROJECT --write-review-template review/observations.json` 建立当前像素观察表。按实际证据填写方向、眼神、接缝、背景、轮廓、合成帧和交互；未检查保持 unknown。实验 phase/arc 不走 --approve，保留离线证据与局限说明。静态背景遮罩避开新旧头完整运动并集。
6. 失败项按 [repair-and-review.md](references/repair-and-review.md) 分流；需要前景分离时先制作和核对逐帧遮罩。标准方向环可用 `repair_head_atlas.py` 输出独立候选，实验 phase/arc 在源素材层处理后重新编译。重跑相应结构与证据检查，比较改善和新增问题。所有合成帧保留来源；降低像素差不代表残影消失。修复失败保留原件和证据，不覆盖素材，不无限换算法或付费重试。没有缺陷则跳过修复。
7. 复制 assets 下五个 `.mjs` 模块，按 [runtime.md](references/runtime.md) 接入目标首屏。完整方向诊断用 diagnosticPreview:true；有限方向/实验相位用 experimentalPreview:true，并展示 preview.notes。检查双向、跨顶部、回正、缩放与遮挡。动静态同坐标，不把新头接回另一张图旧身体。用户要求不打开浏览器时记录未测试，继续离线检查并交付入口，不填写交互通过。
8. 全部检查满足后，`audit_head_atlas.py manifest.json --root PROJECT --review review/observations.json --approve` 写入工程检查记录，再用 `validate_head_manifest.py manifest.json --root PROJECT --require-ready` 验证。正式页面不传诊断开关；未检查或报告/底图/图集变化时运行时保留静态图。用户仍做最终体验验收。

首轮必须按 iteration-delivery.md 交付实际可完成的候选或合成诊断；不因尚未达到正式 ready 而省略可体验版本。说明未完成项与原因。“生成完成”“网页能动”“工程检查通过”“用户验收通过”分开报告。

## 生成入口

读 [zenmux.md](references/zenmux.md) 与 [prompt-patterns.md](references/prompt-patterns.md)。模型/模式分别校验；Max 显式设置扩写模式。先 --write-input-review 生成未审查模板，实际检查后 --dry-run，最后按已有授权提交。参考图/视频/音频与首尾帧互斥；替换坏参考可用 reviewed-replacement 修复，分段有独立阶段，不强制复用失败像素。

通过 zenmux_config.py set 隐藏输入 Key，不写项目。所有付费按已有授权和 --budget，不自动重试；--job-id 只查询旧任务。POST前占次数，超时不自动退还，不换预算绕过上限。留存实际发送的媒体、身份基准、输入观察、提交文字与服务返回扩写；未返回扩写不等于模型原样使用文字。新策略按 [generation-evaluation.md](references/generation-evaluation.md) 对照评估，不能从单例宣称普遍成功。

## 修改 Skill 后验证

运行 `python -m unittest discover -s scripts -p "test_*.py"` 和 `node --test tests/*.test.mjs`。配准/光流测试需安装可选依赖，不把 skip 当通过。再用保留的失败素材检查错误是否被拒绝、修复候选是否保留来源与坐标、文档示例是否可执行。代码测试不等于视频生成成功率或视觉验收。能力边界见 [architecture.md](references/architecture.md)。
