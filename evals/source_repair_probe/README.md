# 独立一次引用修复实验

本目录由AI准备，使用r6真实record_assessment动作作母本，仅清空knowledge_citations产生反例。它不是r5原请求重放，不是专家验证，不提供新图像或像素访问，也不评价器物归属正确率。

prepare_and_validate.py离线读取冻结run与真实请求回复，调用原Engine门禁生成失败反馈，并准备完整文字请求与原注册record_assessment_required Schema。它不调用网络、不改原件、不补引用或结论。母本、快照、准备包和提示必须匹配。

独立评测的可选依赖为 `jsonschema==4.23.0`，供准备脚本及冻结作用域校验使用；运行这些评测入口时需提供它。本轮真实Spark试验将其安装到独立 `--target` 目录，并仅由评测进程通过 `PYTHONPATH` 引入，生产venv未改。`source-r6-probe-01` 使用的旧冻结快照仍保留更新前的README；本段是事后的依赖说明，不代表实际运行使用了更新后的文档或源码快照。

```sh
PYTHONDONTWRITEBYTECODE=1 python -B evals/source_repair_probe/prepare_and_validate.py \
  --repo . --run /path/main8b-r6/final-run.json \
  --record-request /path/main8b-r6/requests/request-04.json \
  --output /path/prepared-counterexample
```

独立runner最多发出一次真实文字模型请求，调用既有LocalModel.complete(messages, 90)，保持原native_schema分支、2500 action tokens、90秒总限时。准备包必须逐项匹配重新生成的冻结反例；严格结构化输出及compact模式未开启时拒绝调用。成功与失败都保存，不进行第二次修复，不调用build_opinion，不改变生产预算。

只有主代理确认服务就绪后运行以下命令；准备脚本或测试不会自行发送真实模型请求：

```sh
CIZHENG_STRUCTURED_OUTPUTS=1 CIZHENG_COMPACT_ACTIONS=1 \
CIZHENG_DISABLE_THINKING=0 PYTHONDONTWRITEBYTECODE=1 \
python -B evals/run_source_repair_probe.py \
  --prepared /path/prepared-counterexample \
  --run /path/main8b-r6/final-run.json \
  --record-request /path/main8b-r6/requests/request-04.json \
  --output /path/one-shot-result \
  --model-url http://127.0.0.1:8005/v1 \
  --model Qwen/Qwen3-VL-8B-Instruct \
  --server-identity /path/already-saved-server-health.json
```

server-identity是可选的既有本地JSON声明，文件SHA和来源单独标明，不被当作已认证服务身份。runner也记录同一次HTTP响应里的cizheng_runtime与LocalModel.identity，不额外请求health，不保存Authorization等HTTP头。未识别的HTTP错误正文不导出；匹配原Schema的422保留原受控错误内容及费用。

输出包括完整messages、实际HTTP JSON请求、注册Schema及SHA、原始回复文本、usage、finish_reason、耗时、原始成功/受控422 HTTP响应和母本SHA。随后通过本目录prepare_and_validate.py对模型回复做冻结证据作用域校验；字段类型、观察编号、读取版本和来源门禁均保持。模型可自行引用或真正删除来源转述；通过只意味着这个AI编辑文字反例的合同修复，不证明原r5请求获救、图像判断改善或专业质量通过。

所有输出目录必须是新目录。一次模型请求失败、截断、native拒绝或回复未通过门禁时，进程非零退出并保留失败摘要，不增加尝试次数。测试仅用明确HTTP MockTransport，不调用GPU。
