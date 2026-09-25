# ZenMux 生成接口与离线预检

先读 generation-planning.md 和 prompt-patterns.md。脚本仅调用 ZenMux 原生协议，不是 fal/MiniMax 直连客户端。参数依据核对日期 2026-09-24；模型、通道、模式分别建档，dry-run 不证明服务端已接受。

## 模型参数

| model | 分辨率 | 整数时长 | 扩写 |
|---|---|---|---|
| minimax/minimax-h3-max | 480p、768p | 5–15秒 | 显式 extra.prompt_expansion_mode |
| minimax/minimax-h3 | 768p、2K | 4–15秒 | 未建档同名扩写选项 |

默认仍为 H3 Max，首次成本默认5秒/768p。表内合法值不等于预算授权。其它模型先添加有官方依据的适配，不继承同名前缀的参数。frames 不支持；seed 不承诺确定性。提示词上限7000 Unicode字符，超长拒绝，不静默截断。

Max 扩写选择 disabled / balanced / quality，实际嵌套发送：
```json
{"extra":{"prompt_expansion_mode":"disabled"}}
```
disabled 是精确动作对照的起点，未证明普遍更好。旧 spec.extra 会展平到请求顶层；新版只允许已建档的嵌套选项。服务拒绝时修适配，不能偷偷删参数并重发。

首尾模式使用 first_frame、可选 last_frame 或 loop_frame:true；return_last_frame 仅要求返回尾图。参考模式使用 reference_image(s)、reference_video(s)、reference_audio(s)。任何参考角色与首尾角色互斥。Skill 不提供单尾图规划路线，即使原厂 API 支持也不猜前置动作。

首尾模式实际比例由图决定；ratio 不是裁图操作。参考模式显式选输出比例。新输入必须本地可查看并按实际字节绑定；远程媒体先下载。预检：图片256–5760像素、比例0.4–2.5、每图≤30MB；参考图≤9、视频≤3、音频≤3，总数≤12；视频H.264/HEVC、23.976–60fps、每段2–15秒；同类视频/音频总长≤15秒，视频≤50MB、音频≤15MB；编码请求≤64MB。探测需ffprobe，不为通过检查静默改素材。

预检同时核对真实格式与 MIME：图片 JPEG/PNG/WEBP，或当前 Pillow 可解码的 HEIC/HEIF；视频 MP4/MOV，音轨若存在须为 AAC/MP3；音频 WAV/MP3。GIF、BMP、MKV、FLAC 等不因本地能解码就允许提交。格式不符时在占预算前报错，需要转换则另存副本并重新建立输入观察。

## 新请求流程

复制 zenmux.example.json / zenmux.entry.example.json / zenmux.upper.example.json / zenmux.reference.example.json / zenmux.segment.example.json 中适合的路线到项目，填写实际目标与文件。媒体/证据路径相对 spec。示例没有附带已通过的输入观察。

默认使用 motionPlan.promptSpec；按 [prompt-patterns.md](prompt-patterns.md) 先导出完整文本：
```text
python scripts/build_motion_prompt.py PROJECT/source/request.json --output PROJECT/build/prompt-review
```
生成请求实时使用同一组装器，不需要把导出的文本再粘贴回 spec。修改规格会改变请求及输入观察绑定；不要把旧观察复制成通过。手写 prompt/prompt_file 仍可使用，不能同时提供 promptSpec。

创建未审查模板，identity 指原始身份基准：
```powershell
python scripts/generate_zenmux_video.py --spec PROJECT/source/request.json --identity PROJECT/assets/original.png --write-input-review PROJECT/source/input-review.json
```
输出须与 motionPlan.evidence 一致，不覆盖旧观察。模板不联网、不占预算；实际查看后按 generation-planning.md 填写。不要自动填 pass。

预检、提交：
```powershell
python scripts/generate_zenmux_video.py --spec PROJECT/source/request.json --budget PROJECT/build/generation-budget.json --dry-run
python scripts/generate_zenmux_video.py --spec PROJECT/source/request.json --budget PROJECT/build/generation-budget.json --output-dir PROJECT/source/run-01
```
预检显示真实提示词、隐藏媒体的 body、输入绑定、仅文字控制项、预算和生产阶段。它不证明动作正确，也不产生额外授权。旧 Markdown 检查表需迁移为请求绑定 JSON 才可新提交；旧任务恢复不受影响。

## 密钥与累计预算

zenmux_config.py status / set / path / clear 管理用户目录Key；set为隐藏输入，ZENMUX_API_KEY可覆盖。Key不进项目、命令参数、提示词或审计文件。

```json
{"schemaVersion":1,"purpose":"一个主体的一次动作试片","maxSubmissions":1,"attempts":[]}
```

默认单次5秒、总秒数maxSubmissions×5、H3 Max、768p。按已有授权扩大原文件 limits，保留 attempts 并记录 changeReason；不能新建预算清零。参考视频/音频可能产生输入费用，需在同一 limits 记录 allowReferenceMedia:true 与 changeReason。此项声明输入费用已计入授权范围，不自动计算金额或累计输入秒数，不得宣称完整财务封顶。

POST前排他占预算；失败、超时或无id不自动退还/重发。同一请求不重复提交。旧任务用 --job-id ID --output-dir 原目录，仅GET/下载，不占次数；恢复时 --spec 被忽略，不重新生成。无id的不确定提交先查服务端，不能删记录假装未提交。

## production 本地阶段

- pilot：首次；同一预算不可反复标pilot。
- repair，inputPolicy:source-frames（旧默认）：sourceVideo、defectEvidence、sourceInputs把真实首尾绑定旧片解码帧，适合补接缝。
- repair，inputPolicy:reviewed-replacement：保留 sourceVideo、defectEvidence，增加 changeReason、inputReview。允许重新准备合适参考或换动作参考；新观察必须绑定实际请求，不能强制继承失败图。
- segment：首段仍为pilot；后续段用 previousVideo、previousFrame、inputReview。首图必须是前段声明帧的实际解码图，尾图可另备。previousFrame可为裁止点而非物理末帧；记录前段裁止范围。它不证明输出接缝。
- expansion：其它主体扩展沿用 root、pilotManifest、pilotRequestSha256、sceneId、可选pilotBudget的实际来源/场景/ready校验。实验候选不是量产通过。

阶段与输入检查不替代预算授权。所有修复/分段累计。

## 输出

request-audit.json保存提交文字、实际参数、媒体请求值哈希、计划与控制报告。提交前将实际发送的首尾图或参考媒体、原始身份基准和观察表原文保存到本次输出的 inputs/，inputArchive 记录相对路径及字节哈希；以后修改原文件仍可复盘。观察表副本中的基准路径仍相对原位置，查看存档应使用 inputArchive.identityBaseline 定位副本。留档失败不发POST；若已占预算则保留预留记录，人工核对后再恢复，不能自动重试。

provider-observation.json保存服务返回的expanded_prompt（隐藏媒体URL）、其哈希及seed；缺失/null记为not-returned-or-undisclosed，不代表未扩写。恢复轮询保留已取得的扩写证据。历史任务只恢复已有留档，不伪造旧首尾图或旧扩写内容。

submission.json、job.json、result.mp4与可用尾帧保留原件。先检查母版，再选择正式方向、有限方向、实验相位或播放诊断。首尾姿态与接缝速度分别检查。

依据：[ZenMux原生视频](https://zenmux.ai/docs/api/zenmux/generate-videos-native.html)、[MiniMax参数](https://platform.minimax.io/docs/api-reference/video-generation-v2-create)、[H3 Max扩写](https://fal.ai/models/minimax/h3-max/image-to-video/api)。新增适配通过离线测试不等于通道实测或跨素材生成成功率。
