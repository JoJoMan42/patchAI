# Evaluation results

Run `final`, 159 runs.

| Model | Fix rate | 95% interval | First try | Fake fixes | Unreadable | Guard blocked | Avg attempts | Avg time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| patchai-3b | **79%** (42/53) | 67%–88% | 77% | 15% | 0% | 4% | 1.4 | 7s |
| qwen2.5-coder:3b | **42%** (22/53) | 29%–55% | 30% | 30% | 0% | 17% | 2.3 | 10s |
| qwen2.5-coder:7b | **74%** (39/53) | 60%–84% | 74% | 4% | 0% | 44% | 1.5 | 15s |

## Fix rate per vulnerability type

| Type | patchai-3b | qwen2.5-coder:3b | qwen2.5-coder:7b |
| --- | --- | --- | --- |
| CWE-22 Path traversal | 100% | 43% | 100% |
| CWE-327 Weak cryptography | 56% | 22% | 100% |
| CWE-502 Unsafe deserialization | 100% | 100% | 56% |
| CWE-78 Command injection | 100% | 29% | 100% |
| CWE-79 Cross-site scripting (XSS) | 100% | 0% | 0% |
| CWE-798 Hard-coded secret | 0% | 43% | 71% |
| CWE-89 SQL injection | 100% | 43% | 86% |

![Fix rate](fix_rate.png)

![By type](by_cwe.png)

![Quality](quality.png)

![Failures](failures.png)
