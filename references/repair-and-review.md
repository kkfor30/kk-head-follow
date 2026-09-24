# 程序修复与工程检查

所有素材路径相对 `--root PROJECT`；manifest 单独指定。`--output` 必须是尚不存在的独立目录。原件不修改。每次只修明确问题，避免同时改多项而无法定位副作用。

本文 repair_head_atlas.py 面向标准方向环。实验 phase/arc 的索引与覆盖语义不同，先在源素材层处理后重新编译，重新核对 preview.samples；脚本会拒绝把候选当完整方向环修复。

## 遮罩

`staticMask` 与 `motionUnion` 为 atlas cell 同尺寸二值 PNG（0 / 255）。staticMask 标记全片始终静止的背景；motionUnion 覆盖底图旧头、全片新头、耳朵/发丝/胡须及颈部运动。两者至少留 2 像素隔离，Agent 必须查看全帧核对。程序只能校验尺寸、相交与采样面积，不能识别人或动物，不能拿移动耳朵当背景色差。

复杂背景缺少干净底图或逐帧遮罩时，先准备素材，不能用全矩形 Alpha 伪装抠像，也不能用近白替换处理深色背景。

## 修复入口

### 先选择下一步

| 已确认问题 | 下一步 | 不能据此认定 |
|---|---|---|
| 仅亮度变化 | 有限校色 | 纹理漂移也能校色修好 |
| 固定区域整体偏移 | 有限配准，单独复查颈根 | 背景对齐等于身体对齐 |
| 背景被重画 | 前景遮罩与干净底图合成 | 扩大羽化能修复 |
| 遮罩碰到补丁羽化边界 | 回源重新编译更大不透明区域 | 光流失败等于视频无用 |
| 源视频本身截断鼻口、耳朵 | 标记缺失帧和方向；核查其他真实片段 | 扩大抽帧矩形能恢复缺失像素 |
| 动作停留、方向完整 | 重新标定和重定时，再检查新邻接帧 | 提高 runtime 平滑能去掉停留 |
| 小接缝 | 相近原生端点与受约束补帧 | 像素相似等于运动趋势一致 |

按 [iteration-delivery.md](iteration-delivery.md) 做有限、可比较的程序处理并交付候选。诊断页不等于修复完成，但首次不要求消除全部瑕疵才提供体验。原生素材缺少必要姿态或像素时标明范围，不无限试算法或自动追加生成。

### 本地前景遮罩候选

安装可选依赖 rembg、onnxruntime、opencv-python-headless；准备本地 u2net.onnx 后运行（脚本不下载模型）：

```text
python scripts/prepare_head_mattes.py --video source.mp4 --output build/mattes --model-dir LOCAL_MODEL_DIRECTORY --start 0 --end 120 --size 512 512
```

输出每帧软遮罩、解码帧、接触表、源/模型哈希与触边告警。坐标是整个缩放后的源视频，接入 atlas 前必须按 sourceTransform 裁切对应遮罩。底部身体连接不自动判为头部截断；顶部/侧边告警需要辨别是头、身体还是分割误判。

这是分割候选，不能直接视为毛发抠像通过；检查胡须、耳毛、嘴内部、背景泄漏和时间闪烁。普通 GrabCut 对同色沙发容易误分，不能作为自动通过的替代。源视频已截断的部位，遮罩程序不能补回。

旧头擦除和逐帧遮罩是两项独立工作。背景修补只在旧头被挡住的区域进行，保留其余原背景；传统 inpaint 可能糊掉沙发结构，结果仍需核对，不能自动成为合格 cleanPlate。身体配准必须用固定连接区域，避免对齐脸部而抵消真实转头。未经验证的算法留在项目实验目录，不写成默认修复结论。

```text
python scripts/repair_head_atlas.py assets/frames/manifest.json --root PROJECT --spec repair.json --output PROJECT/build/repaired
```

最小校色 spec：
```json
{
  "staticMask": "review/static.png",
  "motionUnion": "review/motion-union.png",
  "operations": [{"type": "color-offset", "maxOffset": 12}]
}
```

- `color-offset`：在不透明静态区域拟合每通道中位数偏移，最多 12 / 255，修正整块补丁的全局漂移；残留纹理错位或误差变大则拒绝。它也改变主体颜色，须检查肤色和帧间闪烁，不通过扩大阈值处理结构变化。
- `translation`：有纹理的静态背景估计平移，`maxPixels` 默认 3 个 cell 像素，无纹理则拒绝。预乘 Alpha 重采样并检查运动区域露空；仍须核查颈根等固定结构。不修非刚性形变。
- `clean-composite`：提供底图同尺寸的 `cleanPlate` 和按原 atlas 索引排列的逐帧 `masks`（软 Alpha PNG）。前景覆盖到已移除旧头的底图；遮罩进入原补丁羽化/缺失处则拒绝，需先重编译更大绘制区。输出固定场景补丁，不是任意换底色的透明角色。不能一张轮廓遮罩用于所有转头帧。
- `keepFrames`：递增原 atlas 索引，去除停留或无用采样，保留第 0 帧和八个真实方向锚点。若应删的是锚点，先回源视频重新标定。删段后两侧仍需查连续性。

不要只扩大羽化处理失配背景。配准/校色不能恢复时转干净底图与逐帧遮罩；缺素材明确记录。

### 动作节奏候选

已有八个实际方向锚点后，可用 `propose_phase_map.py --folder MATTE_OUTPUT --anchors 八个源帧编号 --head-rect x y w h --output 新报告.json` 分析头部前景内运动量。输出 sourcePhaseProposal 是锚点间的节奏建议，不是姿态角度估计，不直接修改 manifest。头部矩形必须覆盖运动同时尽量排除身体；若相交前景不足会拒绝。

检查旧映射与新建议的顺逆向序列、眼神和局部速度，再把已核对的细分标定写入 phaseSamples。不能仅为消除停顿把错误方向提前显示。工具不推断 315° 到 360° 的缺失上弧，不能把重定时当成闭环修复。完全静止段即使能生成单调建议，也没有创造新姿态。

局部身体变形若另行实现，用 deformation_quality.inspect_inverse_map 检查全部帧的映射折叠、源边界与受保护头部区域；仅抽查锚点会漏掉中间帧折叠。数值通过仍需检查纹理拉伸、时间闪烁和颈部衔接，不自动采用几何候选。

## 小接缝补帧

额外字段示意，编号与相位必须由当前素材实测：
```json
{
  "staticMask": "review/static.png",
  "motionUnion": "review/motion-union.png",
  "phaseSamples": [[0,0],[12,45],[24,90],[36,135],[48,180],[60,225],[72,270],[84,315],[95,350]],
  "bridges": [{"afterFrame":95,"toFrame":0,"count":3}]
}
```

phaseSamples 为 `[atlasFrame, observedDegrees]`，上为 0，顺时针递增，包含全部八方向锚点；不能按时间均分、把回正标上方。补帧仅允许所选路线相邻端点、缺口≤30 个实测方向度、1–8 帧。这是保守的算法适用范围，不是生成参数。

程序检查双向光流往返一致性、对齐残差、位移和映射折叠，再反向采样；每张合成图只用一张源，不叠化两张脸。遮挡填补和源切换仍可能不自然，数值合格只是候选；逐张查看所有 SYNTH 帧及两侧原生帧。新增帧保留父清单、端点和比例。

拒绝后回到原生素材判断能否选更近端点，不盲目放宽阈值。整个上弧缺失、反方向动作或视线缺失不能靠本工具造出。程序优先不等于程序能修复任何缺口。

## 观察表

```text
python scripts/audit_head_atlas.py MANIFEST --root PROJECT --write-review-template PROJECT/review/observations.json
python scripts/audit_head_atlas.py MANIFEST --root PROJECT --review PROJECT/review/observations.json --output PROJECT/review/quality-report.json
```

模板绑定当前清单、底图、图集与 cleanPlate；像素变化后重新输出证据并建立模板，不复制旧通过状态。

1. observations：八个锚点的实际 head 和 gaze，取 up、upper-right、right、lower-right、down、lower-left、left、upper-left；眼神不可辨用 unknown。每项 notes 和 evidence 文件路径。不能把目标方向填成实际观察。
2. checks：directionCoverage（包含中间段和反向检查）、gaze、loop（姿态与速度趋势）、background、contours（旧头/耳发/颈根）、synthetic、interaction。每项 pass / fail / unreviewed、说明、证据。无合成帧也记录已检查来源。程序不解析图片内容，Agent 必须实际查看。
3. backgroundMasks：`{"static":"review/static.png","motionUnion":"review/motion-union.png"}`。对全部底图合成帧检查静态区域颜色与局部边缘：MAE≤5、P95≤15、边缘差≤5。通过只代表采样区符合工程阈值，不能证明头部轮廓自然。
4. resolvedTransitions：像素突变逐个处理。修复后重编译；合理动作差异经查看可填 `{afterFrame,status:"pass",notes,evidence}` 解释，不批量消除告警。

`--approve` 仅在全部条件满足时写入工程检查记录；报告、证据和像素哈希绑定，后续变化失效。新的正式前端需要该记录；旧清单仍能进行离线检查。最终由用户确认体验。

对已通过清单重新检查，出现失败结论或源文件/结构检查异常时，会将旧 quality 撤销为 blocked；即使报告另存路径或本次没有传 --approve，也不会保留旧的通过状态。连续修复继承祖先输入哈希，不能通过再删几帧绕过已变化的遮罩或底图来源。

交互证据覆盖顺/逆时针整圈、两向慢速跨顶部、移动反向、中性回正、缩放、离屏恢复和减少动态。离线 Node 测试不是某个页面的浏览器验收。无法执行浏览器检查时保持 unreviewed，其余修复继续。
