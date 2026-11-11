Task Allocation Rules Between Models
This file lives in the project root. The dispatcher agent reads it before every task and decides who gets it. Draft: adjust it to your framework.
Executors
• Local model (Ollama, qwen3-coder:30b, home server): routine work and edits that follow an existing example. Free and fast, but holds the overall architecture less well.
• DeepSeek (API): medium-complexity tasks where the local model failed twice or a wider context is needed. Paid; code goes to an external server.
• Dispatcher (Antigravity): breaks work into tasks, hands them out, checks the results. Writes code itself only for architectural decisions.
What goes to whom
Local model
• Standard routine tasks where it is hard to go wrong.
• Edits and additions that follow an existing example in a neighboring file.
• Tests for functions that already exist.
• Documentation, comments, renaming refactors.
• Small scripts and utilities.
DeepSeek
• New modules with complex logic.
• Tasks that touch several files at once.
• Anything the local model could not handle after two attempts.
Dispatcher or the senior model
• Architectural decisions: module structure, interfaces between modules, data formats.
• Any change that breaks compatibility.
• Investigating unexpected errors whose cause is unclear.
Rules for everyone
1. Before a task, read this file and the description of the project structure.
2. Do not change the architecture or public interfaces without an explicit command.
3. One task, one commit. Always commit before a serious agent edit so you can roll back.
4. Run the tests after an edit. If there are no tests for that spot, add them first.
5. Record which model did what in the commit message or in the file header.
6. Never include secrets or keys in code or in requests.
When to escalate
• The local model failed twice in a row on the same task: hand it to DeepSeek.
• DeepSeek failed too, or the task touches the architecture: return it to the dispatcher.
• Not sure who should take it: send it up, not down.
What to fill in yourself
• A short project map: which modules exist and what each is responsible for.
• A list of places the models must not touch.
• The command that runs the tests.
• Which of the old comments from the main model support these rules; copy examples here.
