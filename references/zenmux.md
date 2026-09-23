# ZenMux 视频生成规范

此文件是 `generate_zenmux_video.py` 的 ZenMux 参数和提交规则说明。提示词、首尾帧和任务请求必须按这里的约束生成。

## 默认模型与参数

头部跟随默认使用：

| 参数 | 默认值 | 规则 |
|---|---|---|
| `model` | `minimax/minimax-h3-max` | 用户明确指定其他模型时才切换；其他模型参数按其接口规格传递 |
| `resolution` | `768p` | MiniMax H3/H3 Max 使用 `768p` 验证动作；清晰度不足时可显式升到 `2K` |
| `duration` | 显式填写 `5` 秒的小样 | 记录 durationReason；不是 API 隐式默认。延长必须有实际理由、已有授权及相应预算 |
| `ratio` | 从本地参考帧推断 | 可显式指定 `21:9`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16`；远程参考图无法自动读取尺寸，需显式传入，否则回退 `1:1` |
| `generate_audio` | `false` | 头部交互素材不需要音轨 |
| `watermark` | `false` | 禁用模型水印 |
| `return_last_frame` | `true` | 请求可用时返回尾帧，便于确认方向素材终态 |
| `seed` | `-1` | 默认随机；指定整数便于记录；不承诺服务确定性复现 |

MiniMax H3/H3 Max 的分辨率只接受 `768p` 或 `2K`。`frames` 仅在目标模型明确支持时使用；传了 `frames` 就不能同时传 `duration`。不传 `frames` 时必须显式传 `duration`。示例 5 秒是已用过的参数，不是完整一圈的质量保证。

提示词发送前按 Python Unicode 字符数计算，**最多 7000 characters**。超过上限时脚本拒绝提交，并告知当前长度与上限；不得静默截断、删减约束或把提示词拆成模型不支持的字段。提示词应精简重复措辞，保留主体身份、允许动作、必须固定项、方向路径和负向约束。

## 必填 motionPlan

新提交和 dry-run 要求 motionPlan；旧任务 --job-id 查询不需要重建计划。计划不会发送给模型，是本地生产合同。kind 可选 closed-orbit、entry-orbit、upper-arc、diagnostic；详见 prompt-patterns.md。所有计划需要 evidence（相对 spec 的本地输入核对文件）和 durationReason。实际语义仍由 Agent 查看图片核对。closed-orbit 还要求 coordinateSystem=screen、path=clockwise、seamDirection=up、seamPoseVerified=true，并实际发送同一首尾图。entry-orbit 需声明中性进入段，不能称原文件闭环。upper-arc 需真实左上/右上首尾图。

## 图片输入模式互斥

MiniMax H3 的参考图模式与首尾帧模式互斥：

- **参考图模式**：可传一张或多张 `reference_image`，不能同时传 `first_frame`、`last_frame` 或 `loop_frame`。
- **首尾帧模式**：可传 `first_frame` 和可选 `last_frame`。
- **闭环模式**：传 `first_frame` 并启用 `loop_frame`，脚本将同一张图同时作为首尾帧。
- 只传 `last_frame` 而没有 `first_frame` 属于无效请求。

参考图和首尾帧冲突会导致 MiniMax 接口错误（历史错误码 `2013`）。脚本在联网前阻止这种组合。

本地图片会编码为 `data:` URI。大图或视频作为参考素材时优先使用可访问的 HTTPS URL，避免请求体过大。远程参考地址不得写进交付元数据明文。

## API Key 配置

先检查状态：

```powershell
python scripts/zenmux_config.py status
```

通过隐藏输入安全保存到本机配置文件：

```powershell
python scripts/zenmux_config.py set
```

持久配置固定保存在当前用户的配置目录，不跟随 Skill 安装、不写入项目：

```text
Windows: %APPDATA%\kk-head-follow\config.json
macOS/Linux: $XDG_CONFIG_HOME/kk-head-follow/config.json
macOS/Linux（未设置 XDG_CONFIG_HOME）: ~/.config/kk-head-follow/config.json
```

`ZENMUX_API_KEY` 环境变量可以覆盖本地持久配置。路径检查会显示最终用户级配置位置；清理配置：

```powershell
python scripts/zenmux_config.py path
python scripts/zenmux_config.py clear
```

配置检查脚本支持只读 API 连通性检查：

```powershell
python scripts/check_zenmux_config.py --check-api
```

Key 只从环境变量或本机配置读取。不能写入 spec、命令参数、提示词、日志、任务元数据、manifest、网页代码或仓库。

## 请求、轮询和结果

```text
POST https://zenmux.ai/api/v1/videos
GET  https://zenmux.ai/api/v1/videos/{jobId}
```

请求带 `Authorization: Bearer <API_KEY>`。任务为异步流程，状态包括 `queued`、`running`、`succeeded`、`failed`，脚本以 15 秒为默认轮询间隔，默认最长等待 900 秒。超时后保留 job id，只用 `--job-id` 继续查询。新提交必须指定 `--budget`，已有其他任务不再阻止获授权的新片段。预算限制次数、请求秒数、模型和分辨率；不是金额估算，也不是支付授权本身。由 Agent 按用户已经授权的范围准备，例如：

```json
{"schemaVersion": 1, "purpose": "一个主体的方向素材验证", "maxSubmissions": 1, "attempts": []}
```

- 首次 POST 前持久化占用一次，并在输出目录创建 `submission.json`。预算通过排他锁防止并发占用；同一输出另有排他记录，避免不同预算覆盖它。
- 超时、网络错误、服务拒绝或响应缺少 id 均不自动退还次数，不自动重发。同一预算内相同请求也不重复提交。这是提交尝试计数，不能声称每次尝试均已扣费。
- 已有 id 使用 `--job-id ID --output-dir 原目录`，只 GET/下载，不需要预算；错误 id 不得覆盖已有 job.json。旧版本 job.json 也支持继续查询。
- 没有 id 的不确定提交需要核查服务端任务后再处理，不能把“本地没收到”当作“服务端未创建”。锁或预留记录残留时先核查，不自动删除。
- 同一效果任务沿用唯一共享预算，pilot、repair 和重试累计。获授权的后续轮次在原文件保留 attempts、记录授权及用途，再增加对应上限；不得用新预算重新计数。新独立任务才另建预算。详见 [iteration-delivery.md](iteration-delivery.md)。
- `--dry-run` 验证并输出请求预览，不联网、不占次数；媒体内容与远程媒体地址不打印。它不证明生成效果或提供额外授权。

输出 `request-audit.json` 保留实际提示词、请求参数、motionPlan 和媒体请求值的 SHA-256（不保存媒体 URI），便于复盘。另保留脱敏 `job.json`、`submission.json` 与预算记录；请求哈希绑定实际正文和媒体内容，不保存媒体 URL 或凭据。预算 attempts 保留提交前的预留事件，提交所得 id 以输出目录的 submission.json/job.json 为准。

ZenMux 原生协议请求字段：

```json
{
  "model": "minimax/minimax-h3-max",
  "content": [
    { "type": "text", "text": "..." },
    { "type": "image_url", "role": "first_frame", "image_url": { "url": "..." } }
  ],
  "resolution": "768p",
  "ratio": "1:1",
  "duration": 5,
  "seed": -1,
  "generate_audio": false,
  "watermark": false,
  "return_last_frame": true
}
```

`content` 中支持文字、首帧、尾帧、参考图、参考视频和部分模型支持的音频参考。`extra` 可承载所选模型的其他原生参数，但不能覆盖标准字段、互斥规则和 7000 字符提示词限制。

生成器输出 `result.mp4`、可用时的尾帧和脱敏 `job.json`。任务记录只保留 job id、状态、模型、输出路径和更新时间。若请求的尾帧 URL 不存在，后续媒体流程从下载视频提取尾帧。

生成后必须继续运行 `segment_head_motion.py`、检查动作采样帧，再用 `compile_head_atlas.py` 编译局部图集；不能直接把生成视频当作最终网页头部层。

## 运行示例

先将 references/zenmux.example.json 复制到项目制作目录，按实际输入修改并准备抬头接缝图及本地输入检查文件。示例路径相对该 JSON；不要直接把正视原图改名为 up-seam.png。无实际媒体和证据时 dry-run 应报错，这是必需输入检查，不是已可运行的演示素材。

```powershell
python scripts/generate_zenmux_video.py `
  --spec references/zenmux.example.json `
  --budget build/generation-budget.json `
  --output-dir build/zenmux-head
```

检查请求但不提交：

```powershell
python scripts/generate_zenmux_video.py `
  --spec references/zenmux.example.json `
  --dry-run
```

官方接口：[ZenMux Native Video API](https://zenmux.ai/docs/api/zenmux/generate-videos-native.html)。


## 秒数预算与生产阶段

limits 默认 maxSecondsPerSubmission=5、maxTotalSeconds=maxSubmissions×5、models=[minimax/minimax-h3-max]、resolutions=[768p]。超默认范围需记录 limits.changeReason，必须符合用户已有授权，不能为绕过错误自行增大。旧 attempts 缺少 requestedSeconds 时按原始请求核对补录，不把历史当零。当前秒数预算拒绝 frames 请求，不能用帧数绕过时长限制。

spec.production 是本地字段，不发给视频服务：

- 首次 {"stage":"pilot"}，省略同此；同预算不能反复标为 pilot。
- 扩展：{"stage":"expansion","root":"..","pilotManifest":"assets/cat/manifest.json","pilotRequestSha256":"实际请求哈希","sceneId":"共同场景"}。校验已通过清单包含该 pilot 输出视频，并匹配场景。跨预算复用显式提供 pilotBudget（相对 spec）。
- 补片：{"stage":"repair","sourceVideo":"source.mp4","defectEvidence":"defect.md","sourceInputs":[{"role":"first_frame","frame":123},{"role":"last_frame","frame":45}]}。sourceInputs 绑定所有实际首尾图，可带 renderSize、crop 描述提取变换；程序解码源视频并比较像素，不能引用无关视频绕过小样扩展。需要 OpenCV。

--dry-run --budget 路径 同时核对成本与阶段，未提供预算按首次5秒默认检查。真实提交在锁内再次核对。语义身份与用户授权仍由执行者判断，记录不是授权来源。
