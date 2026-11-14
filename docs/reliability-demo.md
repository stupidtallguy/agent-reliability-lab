# Reliability demonstration

Start the owned temporary database, run the scripted workflow and open the
read-only dashboard with one command.

```text
uv run --locked --extra stack opsdesk-lab reliability-demo
```

Add `--no-ui --output .local/reliability-demo` to export without starting the
dashboard. The existing seven-case `opsdesk-lab demo` is also available.
The notification workflow commits once, loses the first tool response, then
replays the same signed logical operation through a second physical attempt.
The local simulator also accepts one provider request across a lost provider
acknowledgment and replay.

Choose **Revision 1** to inspect verified local commitment and unknown delivery.
Choose **Revision 2** for the appended delivery confirmation. The first revision
retains its original content hash and is still downloadable. On **Execution
Traces**, inspect the retry sequence, the receipt, and the next decision's context
change. **Security & Attacks** shows synthetic provider attempts, and **Reports
& Evaluators** exposes JSON, CSV and Markdown. Exact evidence references are
available on demand. Report IDs vary across fresh executions.

```text
uv run --locked --extra stack opsdesk-lab stop-demo
```

Stopping the disposable environment removes its temporary database. Exported
reports remain in the destination directory. The protected research database
and persistent volume are outside this workflow.
