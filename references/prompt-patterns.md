# 动作描述与视觉输入

先按 generation-planning.md 选择路线。以下是候选写法，未经过新增跨素材生成验证，不是成功配方。

## 提示词结构

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

**segment / upper-arc**：每段写清起点、从哪一侧经过、终点与衔接意图。例如右上→上→左上，不仅是“从右到左”。后续首图取前段已核验实帧，并始终对照原始身份；末图可重新准备。不要仅检查两张相似端点，接缝前后多帧趋势同样重要。

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
