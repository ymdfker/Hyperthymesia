# Hyperthymesia

A long-term memory framework.


通用 agent 长期记忆框架，以 MCP 为载体。前台 agent 只读（快照注入或 MCP 读取工具）；后台写入由程序主导、调用便宜模型，
把已完成轮次（用户原话、最终回复、工作区改动）整理成“对象 + 原子事实”。个人记忆跨项目共享，每个项目有自己的项目库。
只用 Python 标准库；每个平台打包成一个可执行文件。

设计与测试记录：`~/Documents/projects/agent-long-term-memory-design.md`（§25 现行设计，§26 复盘，§27 本代码库规划）。

进度：建设中。第 1 步完成：存储、作用域、脱敏、改动采集；第 2 步写入器已移植（程序侧逻辑有单元测试，真实模型回归进行中）。

运行测试：`python3 -m unittest discover -s tests -v`
