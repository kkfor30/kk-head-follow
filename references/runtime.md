# 网页接入

复制 assets 下 head-follow.mjs、pointer-direction.mjs、frame-animator.mjs、quality-gate.mjs 到项目同一目录。通过 HTTP 提供 .mjs 的 JavaScript MIME；不要用 file:// 打开。

```html
<div id="scene" style="position:relative;width:min(100%,1000px)">
  <img id="base" src="assets/base.png" data-scene-id="scene-v1"
       width="1448" height="1086" style="display:block;width:100%;height:auto">
</div>
<script type="module">
import {mountHeadFollowers} from './runtime/head-follow.mjs';
const follower = mountHeadFollowers({
  scene: document.querySelector('#scene'),
  baseImage: document.querySelector('#base'),
  rootUrl: new URL('.', location.href),
  subjects: [{id:'character', manifest:'assets/frames-character/manifest.json'}],
  onState: states => console.debug('head-follow', states)
});
await follower.ready;
// 在组件卸载、切换场景时调用 follower.destroy()。
</script>
```

scene 必须贴合实际图片区域，不要给它额外 padding 或 object-fit 留白；页面响应式缩放由图片与容器一起完成。manifest 中 baseImage/cleanPlate 相对 rootUrl；sheets 相对 manifest 自身路径。

分层场景的 baseImage 是同一批素材实际合成的静态图，不是另外生成的概念图。cleanPlate 删除当前运动角色、保留其它静态层。角色层、回位图和透明帧使用同一场景坐标；先核对静态/首帧差异，再挂 pointer。独立角色页通过后须在用户要求的目标背景和布局中复查。

当前局部 canvas 先画完整 cleanPlate 区域，故多角色绘制矩形重叠会互相覆盖，静态前景也可能被后画角色遮住。--compare 拒绝矩形重叠；不能为了通过而裁掉头部运动余量。需要前景遮挡或动态角色重叠时，改用统一按层顺序绘制的 scene renderer 并单独验证；现有四模块不自动提供这项能力。

每个主体 manifest 的 runtime 可配置：
```json
{
  "smoothTime": 0.14,
  "verticalScale": 1.15,
  "angleHysteresisDegrees": 0,
  "neutral": {"radiusX":20,"radiusY":10,"top":-6,"exitScale":1.35}
}
```

neutral 数值为 CSS 像素，按实际显示大小选择；这是已知案例的默认值，不是人体比例标准。top 以上不触发中性区，防止扫过额头时点头。距离不改变视频姿态幅度。

运行时平滑 3600 步几何角度，再查方向图集；不直接平滑非均匀帧编号。两端跨过正上方走最短角度。每帧只绘制一张真实姿态，不做脸部叠化。

默认不丢弃小角度输入，由 smoothTime 平滑。旧版本默认 3° 死区会使慢速移动积累到阈值才更新，产生粘滞；旧清单显式填写 3 时也应核对是否需要保留。该修复只解决输入延迟，不修复源素材的停留或首尾姿态跳变。

加载失败、系统减少动态时保留 baseImage。触摸 pointer 不驱动；支持混合设备的鼠标。离屏、隐藏页面停止动画，恢复时回中性。异步加载完成后再次检查生命周期，卸载不会留下迟到的 canvas。

ready 返回各主体状态；一个主体失败不阻断其他主体。可用 enabled 回调接入已有页面时序，入场接管完成后才允许 pointer 驱动；本 Skill 不制作入场动画。


## 检查状态与诊断模式

默认只挂载经过 audit_head_atlas.py --approve 的图集，并用 Web Crypto 验证报告、底图、图集及 cleanPlate 的 SHA-256。需要 localhost 或 HTTPS；无 Web Crypto 时保留静态页并报告不可用。--require-ready 还核验证据文件和源素材。改变帧、背景、索引或 runtime 设置后需要重新检查。

旧版清单也不会静默放行。独立诊断页可显式传 diagnosticPreview:true，状态为 diagnostic-preview，可用于检查未通过素材，不能当正式 ready。诊断也需要结构合法。它是首轮完整方向候选的正式交付物之一，可以保留明确披露的视觉缺陷，但不是正式 ready；不得伪造通过记录。按 [iteration-delivery.md](iteration-delivery.md) 区分完整候选、有限方向和合成播放。

可选 phaseSamples 是 [atlasFrame, observedDegrees] 的实测稠密相位，按其映射方向以减少停段；不能用均分时间伪造。无此字段仍按八个实测锚点映射。

## 中性姿态过渡限制

本版本回中性是清层显示静态底图，进入跟随是初始化到目标方向；不是自然回正或正脸到任意方向的过渡动画。方向环不包含所有径向过渡。不要用固定角度绕路、脸部叠化或硬切掩盖这个差异；需要这项效果时按实际素材独立设计并披露未完成项。见 [冻结范围](frozen-scope.md)。
