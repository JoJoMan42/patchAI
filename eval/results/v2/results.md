# Evaluation results

Run `v2`, 212 runs.

| Model | Fix rate | 95% interval | Demo shop | First try | Fake fixes | Unreadable | Guard blocked | Avg attempts | Avg time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| patchai-3b | **87%** (46/53) | 75%–93% | 6/7 | 87% | 6% | 0% | 0% | 1.3 | 6s |
| patchai-3b-v1 | **72%** (38/53) | 58%–82% | 6/7 | 72% | 13% | 0% | 4% | 1.6 | 7s |
| qwen2.5-coder:3b | **49%** (26/53) | 36%–62% | 4/7 | 38% | 23% | 0% | 15% | 2.2 | 9s |
| qwen2.5-coder:7b | **91%** (48/53) | 80%–96% | 5/7 | 91% | 4% | 0% | 14% | 1.2 | 20s |

## Fix rate per vulnerability type

| Type | patchai-3b | patchai-3b-v1 | qwen2.5-coder:3b | qwen2.5-coder:7b |
| --- | --- | --- | --- | --- |
| CWE-22 Path traversal | 57% | 71% | 29% | 100% |
| CWE-327 Weak cryptography | 100% | 56% | 44% | 100% |
| CWE-502 Unsafe deserialization | 100% | 100% | 100% | 100% |
| CWE-78 Command injection | 100% | 71% | 29% | 100% |
| CWE-79 Cross-site scripting (XSS) | 86% | 100% | 14% | 71% |
| CWE-798 Hard-coded secret | 57% | 0% | 57% | 71% |
| CWE-89 SQL injection | 100% | 100% | 57% | 86% |

![Fix rate](fix_rate.png)

![By type](by_cwe.png)

![Quality](quality.png)

![Failures](failures.png)
