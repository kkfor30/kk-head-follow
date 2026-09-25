# 批处理前的真实场景合成

`review_scene_samples.py` 只导出选中的 1–12 张原生帧及真实场景合成，不需要八方向锚点或完整图集。先从母版总览找最大侧转、上/下、颈根最不稳、轮廓最接近邻居的帧，以及拟拼接两侧。不要把时间均分采样当成方向标定。

复用编译 spec 的几何和背景字段，路径相对 `--root`。下面数值仅演示坐标关系，应替换为实测值：

```json
{
  "baseImage": "assets/base.png",
  "sourceSize": [1200, 900],
  "sourceVideo": "source/main.mp4",
  "renderSize": [360, 360],
  "motionCrop": [80, 30, 200, 240],
  "crop": [600, 100, 200, 240],
  "backgroundOwner": "scene",
  "backgroundMode": "preserve",
  "feather": [10, 10, 10, 18]
}
```

```text
python scripts/review_scene_samples.py PROJECT/source/sample-spec.json --root PROJECT --frames 0 24 51 80 --output PROJECT/build/scene-samples
```

帧号是未抽样的 sourceVideo 原生编号；保持 VFR 索引，不按 FPS 推算帧号。保持视频原始像素方向，不自动按旋转元数据转图，与编译器一致。旋转手机素材需要时先另存方向已正确的副本，后续统一使用该副本标定。

输出 contact.jpg、原图、每张完整场景 PNG、颈部与边缘细节 PNG、透明补丁 PNG，以及 scene-review.json。背景处理和羽化复用编译器；报告绑定输入哈希与配置，所有语义观察初始 unknown。脚本不会识别脸、重建背景或自动填通过。

## 透明与遮挡样片

色键片使用 `backgroundOwner: "page"`、`backgroundMode: "chroma-key"`、`keyColor: "#00FF00"` 和 `cleanPlate`。色键参数沿用编译器；最终编译还会检查全帧边框，几张样片不能替代。

已经带真实 Alpha 的片使用 page/preserve + cleanPlate。普通 RGB 片可先只为选中帧准备遮罩，再在配置中增加：

```json
{
  "backgroundOwner": "page",
  "backgroundMode": "preserve",
  "cleanPlate": "assets/clean-plate.png",
  "sampleMattes": {
    "24": "source/sample-masks/00024.png",
    "51": "source/sample-masks/00051.png"
  },
  "foregroundOverlay": "assets/foreground.png"
}
```

此例运行 `--frames 24 51`。每张 matte 是 renderSize 同尺寸的灰度 L PNG，白色保留主体、黑色去背景；不允许脚本猜比例或自动拉伸。普通 RGB 输入的每个选中帧都需相应 matte。cleanPlate 与 foregroundOverlay 必须与原场景同尺寸；前景 PNG 要有真实 Alpha，并仅保留应遮住角色的前景物体。没有遮挡就省略 foregroundOverlay。

`sampleMattes`、`foregroundOverlay` 是此工具的样片字段，不会自动进入编译器或网页。样片可行后：

1. 将同一分离方法扩展到所有使用帧，检查发丝、毛发、眼镜、颈部和时间连续性。已有可用本地模型时可按 [repair-and-review.md](repair-and-review.md) 制作逐帧候选遮罩；不默认下载模型。
2. 原片带 Alpha/色键时可直接按 page 编译；RGB + 外部遮罩按该文档的 `clean-composite` 输出绑定固定场景、保留来源的独立候选，遮罩按 atlas 来源裁切和排序。该修复入口目前只支持标准方向环，有限方向片需先在素材制作端输出真实 Alpha，不能把样片字段直接当作全片支持。
3. 需要固定前景遮挡时，在网页同坐标容器内增加位于所有动态 canvas 之上的透明前景层，保持同样缩放和位置。当前清单不会自动管理它，必须核对合成和实际页面层级。

检查时先看原尺寸细节，再看最终显示大小：深色背景留意亮边和色溢；浅色背景留意灰边；复杂背景留意旧头、纹理断裂和矩形色块。确认颈根由身体承接，不能让 cleanPlate 的背景透过胸口。单角色检查后还需检查多角色组合和真实遮挡。
