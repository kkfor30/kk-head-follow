# 连续头部与视线视频的生产方案

目标是在主体前方的有限视线范围内完成屏幕平面的顺时针圆周轨迹：上→右上→右→右下→下→左下→左→左上→上，中间不断开、不在方向点停留。横向用真实转脸（yaw），纵向用抬低头（pitch）；允许自然侧倾，但仅摆头或转眼不能替代方向变化。左右始终指屏幕方向。不会要求头颅水平自转露出后脑勺。

输入决定身份、表情、嘴部状态、配饰和身体姿态，只规定所需头眼运动；不预设闭嘴、微笑或水平头部。保留完整头颈和运动余量，镜头和身体保持固定。

## 选择一个明确方案

优先复用已验收素材的真实请求、首尾图和后处理记录。成功如果依靠后续补上弧，不能归因于一句主提示词。

- **closed-orbit**：先有已核对的抬头接缝图，将同一图实际作为首尾约束。整片从上方开始、连续走一圈回到同一上方姿态。正视原图不是上方接缝图；不能只改字段称它为抬头。准备接缝图的来源和额外成本须说明，不默认悄悄生成。
- **entry-orbit**：只有正视原图时可选择进入段，再完整走上→上一个周期。整个文件首尾不必一致，但内部必须存在完整周期；进入段排除。这个方案更依赖模型执行，不能靠裁掉尾部凭空闭环。
- **upper-arc**：仅在已有主方向素材基本可用、程序不能可靠补小接缝时，采用主视频实际左上/右上帧作为首尾参考补上弧。两侧与主片的衔接仍要查。
- **diagnostic**：可选的单轴诊断，不能交付完整方向跟随；不是默认必经成本。

默认显式选择 5 秒作为低成本小样，不保证动作一定完整。延长需有具体理由和对应预算，不能仅凭“可能更稳”自动加长。无接口证据不猜时长范围；先 dry-run 核对请求，候选小样经检查后才扩展多个主体。

## 同一上方首尾的候选提示词

下面是本轮纠正生产逻辑后的候选，尚未通过新素材生成验证，不能保证模型一次完整执行。仅用于真实首尾图都是同一抬头姿态的 closed-orbit：

```text
Locked camera, same subject and composition as the supplied reference. Preserve the subject's identity, original expression and mouth state, appearance, lighting and background. Keep the torso, shoulders and neck attachment in place, with the entire head and its movement inside the frame.

Starting in the supplied upward-looking pose, make ONE smooth clockwise circular sweep of the viewing direction in the screen plane. The head and both eyes track the same direction throughout this single unbroken motion. The trajectory continuously curves from above the camera toward screen-right, below the camera, screen-left, and back above the camera, passing through every intermediate diagonal without stopping or resetting at any direction. The head turns with the horizontal component and the chin lifts or lowers with the vertical component; the face remains visible. Use a natural comfortable range and an even progressing pace. Do not substitute sideways rocking, repeated left-right glances, or separate held poses for the circular sweep.

Both eyes follow where the face is turning, including above and below; do not maintain eye contact with the lens or glance back at the viewer during the sweep. Keep the motion continuous through the final upper-left arc into the supplied upward-looking final pose, matching the initial head orientation, chin height and gaze. Do not add a return to a neutral camera-facing pose. Preserve the original scene content, with no visible tracking object, marker, text, camera movement or body movement.
```

不要同时要求“眼睛始终朝镜头”和“头眼一起追踪方向”。尾图约束只约束姿态意图，不保证回到原像素、速度一致或眼神正确，必须查成片。

entry-orbit 应把起始与结束句替换为明确进入段：从原中性姿态平滑进入上方视线，再完成一次连续圆周，最后回到该上方方向。不能写 supplied upward starting pose，不能宣称其文件首尾闭合；对内部周期逐帧核验。其 motionPlan 设置 firstPose=neutral、cycleStart=up、cycleEnd=up、excludeEntry=true。

## 上弧候选

仅在实际同时发送首尾图时使用：

```text
A locked close-up of the same subject. Starting from the supplied upward-left pose, make one continuous gentle turn through above-center into the supplied upward-right final pose. Keep the chin lifted and both eyes coordinated with the face toward the same viewing direction throughout. Use an even progressing pace, without a pause or a neutral/downward detour. Preserve the input identity, expression, mouth state, neck attachment, shoulders, background, lighting and framing. Keep the entire head visible and add no object, text or camera movement.
```

中心按实帧标定，不假定恰好时长一半；实际首尾图约束不等于两侧接缝已通过。

## 提交前与生成后

记录 motionPlan、本地输入姿态核对文件、实际提示词、首尾图、画幅、时长和预算。return_last_frame 仅返回尾帧，不是 last_frame；参考图模式和首尾图模式不能混用。细节见 [zenmux.md](zenmux.md)。不让输入中性与要求上方首尾的矛盾进入付费请求。

生成后先查全画面，再查局部：是否完整经过实际方向、眼神是否与脸一致、是否有停留/反向/回正、是否新增物体、身体和背景是否漂移。双眼看不清就记录未知。接缝检查至少前后多帧的姿态及运动趋势，不只比第 0 帧与最后帧。

基本可用后按 [repair-and-review.md](repair-and-review.md) 先做程序处理。背景和后处理造成的残影不直接归咎于源视频；大段姿态缺失不能靠插帧或改标签造出。需要新增生成时依据已经存在的用户授权和次数预算，不自动重试。
