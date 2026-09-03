# accounts/ —— 账号品牌锁（每号一等公民）

一个账号一个子目录：`accounts/<id>/brand.json` + `accounts/<id>/references/`。

```
accounts/
  <id1>/
    brand.json        # 该号专属品牌锁（视觉 + 文案 + 参考图）
    references/       # 该号赞最高 top-3 封面（作视觉参照）
  <id2>/
    ...
```

## 生成方式
```bash
python pipeline/brand_analyzer.py analyze \
    --account <id> \
    --cover-dir <该号历史封面目录> \
    [--corpus <该号文案语料.txt/.md 或目录>] \
    [--label "账号展示名"]
```
查看：
```bash
python pipeline/brand_analyzer.py show --account <id>
```

## 约定（硬约束）
- **账号无关**：代码不写死任何账号；缺账号/缺锁 → 直接报错，不默认兜底（防串味）。
- **数据不出本机**：色板本地 K-Means；文案优先本地 Ollama（qwen3-vl），失败降级启发式，全程不联网、不调 GLM/智谱。
- **brand.json 是账号私有本地数据，已 git 忽略**（见 .gitignore），不随公开仓库上传。

## `_locked` 保护
分析结果可被 `--refresh` 覆盖；若运营人工确认某版风格后把 `brand.json` 里 `_locked` 设为 `true`，
后续 `--refresh` 也会**整体保留旧值**；细分可用 `_visual_locked` / `_copy_locked` 只锁视觉或只锁文案。
