# Hyperthymesia

A long-term memory framework.


General long-term memory for agents, served over MCP. The front agent only reads (snapshot injection or an MCP read
tool); a background writer, driven by the program and a cheap model, turns finished turns (user words, final replies,
workspace changes) into objects and atomic facts. Personal memory is shared across projects; each project has its own
store. Standard library only; shipped as one executable per platform.

Design and test record: `~/Documents/projects/agent-long-term-memory-design.md` (§25 current design, §26 review, §27 this codebase).

Status: under construction (step 1 of design 27.4: storage, scopes, redaction, change capture).

Run tests: `python3 -m unittest discover -s tests -v`
