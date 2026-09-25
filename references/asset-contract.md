# 编译合同（schemaVersion 3）

编译 spec 使用底图坐标与保持比例后的工作视频坐标。mainAnchors 一律是**原始主视频绝对帧编号**；directionFrames 则是编译结果中的编号。不要混用。

## 已有视频的完整例子

下例为有专用上弧的单主体配置；数值必须按实际素材标定，文件路径相对 --root：

```json
{
  "sceneId": "scene-v1",
  "baseImage": "assets/base.png",
  "sourceSize": [1448, 1086],
  "sourceVideo": "source/head-main.mp4",
  "upperVideo": "source/head-upper.mp4",
  "outputDir": "assets/frames-character",
  "renderSize": [360, 360],
  "motionCrop": [85, 45, 190, 210],
  "crop": [745, 115, 190, 210],
  "eye": [836, 218],
  "mainAnchors": [18, 24, 36, 42, 54, 60, 66, 84],
  "upperStep": 2,
  "upperMidpoint": 40,
  "backgroundOwner": "scene",
  "backgroundMode": "fit-edge-light",
  "feather": [10, 10, 10, 18],
  "columns": 8,
  "framesPerSheet": 64,
  "runtime": {"smoothTime": 0.14},
  "calibration": {"kind": "reviewed-samples", "evidence": "source/contact-sheet.jpg"}
}
```

- renderSize 是正整数（方形）或 [width,height]，比例必须匹配视频。缩放不负责修复生成过程中的构图漂移。
- motionCrop 是缩放后视频中的 [x,y,w,h]；crop 是最终底图中的 [x,y,w,h]，二者 w/h 相同。
- 输入 ROI 到底图的变换应在制作记录中保存；sourceTransform 记录最终使用的 renderSize 与 motionCrop。
- eye 输入底图像素，必须在 crop 内；manifest 存归一化坐标。
- 八个 mainAnchors 从上顺时针依次是上、右上、右、右下、下、左下、左、左上，必须严格递增，不靠均分时长猜测。
- upperStep 对原视频抽样；upperMidpoint 是**抽样后**的正上方编号。
- mainRightFrame / mainLeftFrame 不再必填；若旧 spec 提供，它们必须等于 mainAnchors[1] / [7]。
- feather 为左、上、右、下四边宽度，不是假定上下相等。
- 背景规则只见 [background-delivery.md](background-delivery.md)。page 路线额外要求 cleanPlate 文件路径。
- calibration 是标定证据来源，不是脚本赋予的视觉合格证书。

没有专用上弧时省略 upperVideo/upperStep/upperMidpoint，以 sourceRange: [start,endExclusive] 选择主视频闭合路线；默认从 mainAnchors[0] 到视频结束。编译器会减去 start 把源锚点转成输出索引。主视频本身若不闭合，不能假装首尾相邻。

## 上弧编排

上弧原方向为左上 → 正上 → 右上。先把上弧端点替换为主片已标定的左上/右上帧，再组装：

```text
upper[midpoint:] + main[upperRight+1:upperLeft+1] + upper[1:midpoint]
```

顶部 0° 接缝来自同一上弧的相邻采样帧。upperSeamScope 明确为 top-center-only；两侧从主片进入上弧的位置仍需检查实际连续性。frameSources 记录每个输出帧的源文件与原始编号，不能用“相邻”标签代替检查。

## 输出与校验

outputDir 必须尚不存在。编译先写入同级临时目录，成功后发布整套图集；失败不覆盖已有候选。新版本编译保留所有原始解码帧序号，变帧率输入不会隐式补出重复帧。VFR 的帧号可用于方向标定，但不能把 fps 字段当作其实际时间轴。

输出 manifest、sheet-N.png、neutral.png；透明模式另有多底色接触表。manifest 保存：
- schemaVersion、sceneId、baseImage、底图哈希和尺寸；
- crop、eye、frameCount、columns、framesPerSheet、sheets、directionFrames；
- sourceRange、upperSource、upperMidpoint、upperFrameCount、上弧中心接缝声明；
- frameSources、sourceHashes、sourceTransform、calibration；
- background、cleanPlate、runtime。

neutral.png 仅供素材比对；运行时回正清空画布，不再覆盖一张低清正脸。

校验实际图集容量、每个有效 cell 的 Alpha、锚点严格递增、眼睛位置、源哈希与底图绑定；忽略最后一张 sheet 的空白填充格。多主体 --compare 需同一底图且绘制区不重叠。技术检查不能判断 cleanPlate 是否确实清掉旧头或人脸是否自然。


## 编译后必须检查首尾及跨源拼接

运行 `inspect_atlas_seams.py manifest.json --output seam-review`，保留 `seams.json` 与边界前后四帧图。报告比较整块补丁的相邻像素变化并标记异常，同时始终输出首尾边界。数值只作排查依据：相似度低可揭示突跳，相似度高也不证明抬头姿态、动作速度或眼神连续。所有跨源接点都要检查。

同样标为“上”的两帧，仍可能存在头部倾斜、下巴高度、颈部伸展和眼神差异。无 upperVideo 时，sourceRange 的最后帧和第一帧尤其不能默认可接。先实测；有断点就记录素材缺口，不能用增加阻尼、帧叠化或搜索外观相似帧充当完整修复。

## 工程检查与修复候选

编译输出 quality.status=candidate、circular=false；结构校验不颁发视觉通过。只有 audit_head_atlas.py --approve 完成内容绑定的检查后正式前端才启用。旧版图集可离线检查，或在显式诊断模式打开。

可选 phaseSamples 按输出 atlas 编号记录 [frame, degrees]，从 [0,0] 开始严格递增，包含八方向锚点对应的 0、45……315 度，尾部小于 360；重排后必须重新映射。quality 在重编译或程序修复后归为 candidate，不继承旧结论。

repair_head_atlas.py 可保留原件并生成独立候选；frameSources 的 synthesized/repair 记录插帧来源。修复与工程检查流程见 [repair-and-review.md](repair-and-review.md)。
