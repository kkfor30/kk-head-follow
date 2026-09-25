# 动作描述与视觉输入

先按 generation-planning.md 选择路线。以下是候选写法，未经过新增跨素材生成验证，不是成功配方。

一次只驱动一个角色；静态邻居或场景可作必要上下文。输入需要看清头眼并留足运动范围。若需要眼神和原图表情兼容，先按 [gaze-and-rest.md](gaze-and-rest.md) 区分保持表情与保持注视方向。不要同时要求全程看镜头和看向画外鼠标。

## 用同一规格生成提交文本

默认在 motionPlan 中填写 promptSpec，并删除请求顶层 prompt/prompt_file：

```json
{
  "promptSpec": {
    "subjectDescription": "the illustrated character wearing glasses",
    "startPose": "The supplied character looks upward with a slightly raised chin",
    "endPose": "The same upward pose, expression and mouth state",
    "allowedMotion": "The head turns with the target, the chin rises or lowers, and visible eyes follow that same target",
    "framing": "Full hair, ears, neck and shoulders remain visible with room for both side turns",
    "staticContext": "The adjacent pet, furniture and torso stay in place",
    "background": {
      "mode": "scene-preserve",
      "description": "Preserve the actual dark wall and soft illumination in the input"
    }
  }
}
```

这是有眼镜的插画人物例子，需按真实输入改写；无邻居就省略 staticContext。subjectDescription、startPose、endPose、allowedMotion、framing 和 background 必填。background.mode 为 scene-preserve / chroma-key / alpha-matte；色键模式还需要与实际输入一致的 keyColor（如 #FF00FF）。alpha-matte 表示后续分离前景，不能声称 RGB 输出天然带透明通道。路线选择见 [scene-routing.md](scene-routing.md)。

路径由 motionPlan.kind 派生，避免维护第二套路线。所有 requirements 中 controls 含 prompt 的 expected 会加入实际提交文字，verify 不发送；仅 runtime/compositing/not-requested 的要求也不发给模型。因此 expected 写可观察的动作与外观，verify 写核验办法；要模型遵守的身份、范围和眼神要求须包含 prompt 控制来源。

```text
python scripts/build_motion_prompt.py PROJECT/source/request.json --output PROJECT/build/prompt-review
```

输出 prompt.txt 与 prompt-plan.json（包含实际文本哈希、路线意图、已加入/未发送的要求、未审查状态）。生成入口使用同一函数实时组装，导出后无需粘贴文本。脚本会验证真实文件和请求合同、不调用 API、不占预算。输出目录须为新目录。

脚本拒绝混用手写和结构化入口、已知模板占位符、错误字段及缺少真实首尾等可确定问题。它不会理解所有自然语言矛盾：Agent 仍须检查 startPose/endPose 与图片一致，requirements.motion/loop 与 kind 一致，眼神要求与可见性一致。输入观察表的 promptImageAgreement 正是核对这些问题，不能因组装成功就填 pass。

## 四种常用制作配方

| 制作目标 | 可复制配置 | 实际控制与检查 |
|---|---|---|
| 有可用向上接缝图的完整环 | [zenmux.example.json](zenmux.example.json) | 同图首尾；上→右上→右→右下→下→左下→左→左上→上；检查全轨迹与接缝两侧速度 |
| 只有中性原图 | [zenmux.entry.example.json](zenmux.entry.example.json) | 中性进入与内部完整环分开；默认预留进入/返回时间，编译只用实测完整环 |
| 只补不稳定顶部 | [zenmux.upper.example.json](zenmux.upper.example.json) | 实际左上/右上首尾；全片持续抬头，经上方单向扫过，不再做整圈 |
| 补缺方向、眼神或幅度区间 | [zenmux.segment.example.json](zenmux.segment.example.json) | 实际起终图 + 明确 via；改对应 requirements，说明如何接回已可用片段 |

各文件都有完整 requirements 和 promptSpec，仍需替换真实主体、姿态、文件与幅度。时长不是固定配方；按动作负荷和已有预算选择。结构化路线的百分比是生成意图，不是成片锚点；脚本不会按它抽出所谓“右上帧”。

entry-orbit 可在 promptSpec.timing 写 `{"entryEnd":0.12,"cycleEnd":0.88}`。默认最后 12% 返回中性；如果不需要片内返回，可设 cycleEnd=1，并相应移除中性尾图约束、改写 endPose。只有 cycleEnd<1 才描述返回中性。其他路线不接受 timing 覆盖；想要另一条路线用 segment。不要让实际 last_frame 与声明终态冲突。

已有合适示范时可用 [zenmux.reference.example.json](zenmux.reference.example.json)，先核对示范与目标主体结构是否相容。该模式保留手写文本示例，也可改为 promptSpec；示范模式没有首尾图硬约束。

## 手写提示词入口

从 motionPlan.requirements 提取：实际首图状态 → 允许运动部位 → 连续经过的可见状态 → 幅度与特征可见性 → 固定项 → 终态。身份、表情、嘴部状态沿用输入，不发明年龄、风格或配饰。不单纯追求长或短；删除矛盾与重复，保留具体动作。

```text
Use the supplied images for the same subject, original expression, mouth state,
appearance and framing. The first image shows [ACTUAL START POSE].
In one continuous shot, [ALLOWED PARTS] follow an unseen target along
[PATH IN SCREEN COORDINATES], through [OBSERVABLE INTERMEDIATE STATES],
reaching [ACTUAL END POSE].
The horizontal motion is [DESIRED FACE TURN]; the vertical motion is
[DESIRED CHIN MOVEMENT]. Keep [TASK-CRITICAL FEATURES] readable throughout.
Use [SUBJECT-SPECIFIC RANGE]. Keep [FIXED PARTS], camera and framing stable.
[ENDING AND LOOP INTENT]. No [RELEVANT UNWANTED MOTIONS].
```

替换方括号；不存在的幅度图/中间关键帧不能写成 supplied reference。无可见眼睛的角色不套瞳孔模板。侧倾可为伴随动作，不能替代任务明确要求的转脸。

## 路线写法

**closed-orbit**：实际提交合适抬头图作首尾。描述上→屏幕右→下→左→上的连续轨迹及中间方向。相同首尾仍可能生成静止、往返、反向和停顿，必须核对完整片及接缝两侧速度。

**entry-orbit**：明确从图中实际中性姿态进入上方，再完成整圈。不能写 supplied upward starting pose，也不将中性图改名为 up。文字时间不是精确时序；从实片找进入段，不靠裁切填补缺失姿态。

**reference-motion**：
```text
Image 1 defines the subject's identity, expression, clothing and composition.
Video 1 demonstrates the order, amplitude and coordination of the movement.
Apply that movement to the subject in Image 1 while preserving its appearance.
Adapt the motion to [TARGET SUBJECT'S RANGE]. Keep [FIXED PARTS] stable.
Do not transfer the reference performer's appearance or camera motion.
```

引用编号与实际提交顺序对应。人类示范不能无条件套到动物；示范先核验。该模式与精确 first_frame/last_frame 互斥，不能假装同时拥有两种约束。随包犬视频不是所有主体的默认驱动。

**segment / upper-arc**：每段写清起点、从哪一侧经过、终点与衔接意图。当前 upper-arc 合同为左上→上→右上；反向或其他区间用 segment，不混用上弧字段。后续首图取前段已核验实帧，并始终对照原始身份；末图可重新准备。不要仅检查两张相似端点，接缝前后多帧趋势同样重要。

## 图文一致

- 面部可见不等于眼睛始终看镜头。画外注视不能同时要求持续镜头对视。
- orbit 明确是谁绕什么，区分视线轨迹、头颅自转、身体绕圈和镜头环绕。
- 固定颈根不等于冻结所有颈部像素。身体/背景精确保留优先由合成实现。
- 图片过度仰头、遮眼或已变脸，先换输入，不用文字否定图片。
- 眨眼按用途判断；随时停帧的素材要检查可用区间，不把所有自然动作一概禁止眨眼。
- 眼神、鼻尖、双颊和耳朵可见变化分别核对；像素移动不等于真实转脸。

## 扩写与失败修复

Max 显式选择 prompt_expansion_mode，映射见 zenmux.md。disabled 便于定位手写约束作用；balanced / quality 可对照，名称不代表质量已更好。保留提交文字和服务返回扩写；未返回写 unknown，不能宣称模型原样使用提交文字。

失败定位：输入不适合→修参考；路线歧义→动作示范/必要分段；文字冲突→改描述；仅速度不均→实片标定；仅背景不符→修合成。下一次获授权生成记录主要变量，连续同类失败时改变控制方式，不只叠加禁止句。交付可同时修改多项，但不能据此单独归因。

依据：[MiniMax 首尾提示词指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)、[参考模式指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)。接口字段仍按当前实际服务核对。
