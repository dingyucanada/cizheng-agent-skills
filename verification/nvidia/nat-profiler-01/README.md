# 实际 NVIDIA NAT 时间轨迹

2026-09-28，在本机独立 NAT 1.9.0 环境运行一次真实 `nat validate` 与 `nat eval`。

三条公开软件协议样例保持正确引用、篡改引用与无读取证据三种预期；不是陶瓷样本。每案的 retrieve / verify / workflow 均有真实官方 `track_function` 的 START / END。原始42事件含9个显式SPAN和9个独立原生FUNCTION区间；模型调用、LLM事件和外连均为0。

官方原生Gantt及report把这两层都标成FUNCTION，所以18行／Total calls18不是18次业务工具动作。报告的p50 concurrency4也来自嵌套重叠，不是4案并行；实际配置max_concurrency=1。原始事件类型、UUID与父子关系见JSON，嵌套时长不能相加。

CLI eval总wall16.371秒包括初始化、运行、分析及绘图，不能当作引用函数或模型请求延迟。三个内部workflow区间约47.425 / 3.370 / 2.879毫秒，只有本机CPU软件工作流含义，不用于GPU加速或专业质量比较。ATIF12 steps是用户输入、两个工具步骤及无模型的最终结果。

[原始事件](nat-eval/all_requests_profiler_traces.json)、[执行状态](profiler-status.json)、[NAT原生图](nat-eval/gantt_chart.png)、[公开字节与脱敏范围](redaction-manifest.json)。绝对本机路径已替换；原始与公开哈希分列，图像字节未改。
