# Reliability demonstration

Configure a publication identity once outside the checkout. Use a directory
whose filesystem permissions allow only trusted operators to read the signing
key and modify the trust directory. On Windows, protect the signing file with
an account-specific ACL.

PowerShell

```powershell
$env:OPSDESK_PUBLICATION_PRIVATE_KEY_FILE = Join-Path $HOME '.opsdesk-publication/demo.key'
$env:OPSDESK_PUBLICATION_TRUST_DIR = Join-Path $HOME '.opsdesk-publication/trust'
uv run --locked opsdesk-lab publication-keygen --private-file "$env:OPSDESK_PUBLICATION_PRIVATE_KEY_FILE" --trust-dir "$env:OPSDESK_PUBLICATION_TRUST_DIR"
```

POSIX shell

```sh
export OPSDESK_PUBLICATION_PRIVATE_KEY_FILE="$HOME/.opsdesk-publication/demo.key"
export OPSDESK_PUBLICATION_TRUST_DIR="$HOME/.opsdesk-publication/trust"
uv run --locked opsdesk-lab publication-keygen --private-file "$OPSDESK_PUBLICATION_PRIVATE_KEY_FILE" --trust-dir "$OPSDESK_PUBLICATION_TRUST_DIR"
```

Reuse the same configuration on subsequent runs. Key generation refuses to
replace an existing identity. The dashboard needs only the trust directory.
Start the owned temporary database, run the scripted workflow and open the
read-only dashboard.

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

Authenticated historical revisions retain their original meaning when current
sources change. The dashboard reports a current inconsistency separately and
omits an unauthenticated revision and its successors from the selector.

```text
uv run --locked --extra stack opsdesk-lab stop-demo
```

Stopping the disposable environment removes its temporary database. Exported
reports remain in the destination directory. The protected research database
and persistent volume are outside this workflow.
