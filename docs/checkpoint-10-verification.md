# Checkpoint 10 engineering verification

The starting private `main` commit was `795f135beb34914755e5e80cf98b13e6313c0db5`. This is an engineering review of application 0.9.0 and the 1.0.0 corrections. Evaluator 1.7.0 remains explicit, renderer 2.2.0 remains available, and the experimental default is 1.1.0. The review confers no external approval.

## Reproduction of prior findings

The pre-change Windows 3.11 run of `pytest tests/remediation17 tests/dashboard` against test-owned PostgreSQL 18.6 passed 108 tests. The [AUD16 remediation record](audit-remediation-1.6.md) identifies the exact tests. The checks exercised failed and rejected read carriers, conflicting sealed request hashes and ledger order, the two-slot contradiction case (`A=2, U=0, K=1`, one unknown, 50% coverage), missing implementation identity, malformed manifest and execution envelopes, and identity-free paired observations. Historical controls include evaluator 1.6.0's original read-attribution behavior.

## Findings corrected for the software release

| Finding | Severity | Reproduction and resolution |
|---|---|---|
| ENG10-01 | High | `COMPOSE_PROJECT_NAME=opsdesk-lab` changed the effective project in a read-only `docker compose ... config` check. A workspace could also select another Compose file. `platform/containers.py`, `platform/cli.py` and `platform/testing.py` pin project and packaged configuration and verify labels, storage and loopback port before operating. Regression `test_compose_project_is_explicit_even_with_inherited_override` and the installed demo with that override exercise the fixed boundary. |
| ENG10-02 | Medium | Set objective attribution status to `[]` or `{}` and call `resolve_trial`. The membership check raised `TypeError`. `evaluation/attack_outcomes_v170.py` validates types and classifies the result as unresolved. `test_unhashable_objective_status_is_indeterminate` asserts the precise diagnostic. |
| ENG10-03 | Medium | In an in-memory cohort, replace an eligible score's evidence hash while retaining the original capture. The report counted it toward ASR. `evaluation/reporting_v170.py` checks selected score/capture identity. `test_report_rejects_score_with_unrelated_capture_hash` exercises the report boundary. The PostgreSQL writer already rejected this mismatch for eligible scores. |
| ENG10-04 | Medium | Mark an exposed objective successful while its attribution says `verified_non_match`. Aggregate ASR was unknown, but the legacy supplemental objective summary could still count success. The 1.7.0 report uses verified population resolutions for overall, scenario, category and objective attack summaries. `test_candidate_attack_breakdowns_use_verified_population` covers the contradiction and positive control. |
| ENG10-05 | Medium | Reseal a synthetic evidence copy with a mismatched request journal turn or proposal tool, operation ID or argument hash. Earlier joins verified the outer seal and event identity without checking these inner relationships. `agent/provenance_v3.py` joins them to the original request/proposal and checks proposal-before-dispatch order. `test_consistently_resealed_journal_must_match_decision_and_proposal` uses real MCP captures and asserts exact diagnostics. |
| ENG10-06 | Low | Overview labeled all reports scripted regardless of the manifest. `dashboard/app.py` uses frozen purpose and trial splits. New product demos record a trusted demo marker in the experiment manifest. `test_overview_identifies_purpose_and_split` covers scripted, demo and held-out/live labels with synthetic fixtures. |
| ENG10-07 | Medium | Re-render an archived 2.2.0 report from saved JSON or PostgreSQL. CSV content matched but row order followed JSON object key order. `evaluation/downloads.py` defines deterministic 2.2.0 row order, and candidate CLI exports use the same serializer. The serialized-report regression and archived export checks verify byte parity. |
| ENG10-08 | Low | Press Ctrl+C in a Windows console running `opsdesk-lab dashboard`. Streamlit stopped, but the launcher printed a `KeyboardInterrupt` traceback. The launcher now returns interrupt status 130. `test_dashboard_ctrl_c_exits_without_a_traceback` exercises the interrupt boundary. |

## Scripted demo and UI

On Windows, wheel installations outside the checkout executed the same seven cases under both baseline and guarded configurations on Python 3.11.9 and 3.12.8. Their logical outcomes matched. The baseline completed 5/7 tasks and the guarded run completed 6/7. Attack success was 3/3 baseline and 2/3 guarded. Both recovered the one exposed recoverable fault and had 3/3 attack-outcome coverage. The hijack committed an unsafe effect in baseline and was blocked in guarded. The viewer attempt remained blocked in both, and answer contamination remained possible in both. These are deterministic scripted cases.

Windows 3.12 rendered all seven workspaces in a browser at `127.0.0.1:8501` and initiated downloads for JSON, CSV and Markdown. Windows 3.11 exercised all seven workspaces with Streamlit AppTest backed by the same disposable PostgreSQL service. A read-only session reported `transaction_read_only=on`, rejected a write with SQLSTATE `25006`, and retained the same inventory. The release validator reported 38 development cases and zero held-out cases. The [demo guide](demo-guide.md) provides reproduction commands.

After the CSV ordering correction, reloading final wheel-generated reports `d1471679399a4e4fb59aa7b9ea52df8d` and `aa62770021ff45c7a7c5113f47db4fe7` from disposable PostgreSQL reproduced all three export formats byte-for-byte. The demo stop command succeeded even with an inherited `COMPOSE_PROJECT_NAME=opsdesk-lab`. The demo container and dashboard listener were removed. The protected service remained stopped.

## Windows verification and build

PowerShell setup installed the locked stack on CPython 3.11.9 and 3.12.8. Both interpreters installed the wheel and source distribution into isolated environments and imported from `site-packages` outside the checkout. The built wheel contains the lock and packaged Compose/demo assets. Ruff, formatting, lock validation, Compose configuration, Git checks and a versioned-file credential signature scan passed. The dependency lock changed only the project version. Exact-commit Linux results, POSIX setup, and isolated distribution checks are recorded in [hosted CI](https://github.com/stupidtallguy/agent-reliability-lab/actions/workflows/ci.yml).

| Windows interpreter | Unit | PostgreSQL integration | Full suite | Failed / skipped / errors |
|---|---:|---:|---:|---:|
| CPython 3.11.9 | 579 | 396 | 975 | 0 / 0 / 0 |
| CPython 3.12.8 | 579 | 396 | 975 | 0 / 0 / 0 |

The complete suites used different databases on the same checkpoint-owned, temporary PostgreSQL 18.6 instance. Unit checks were rerun separately after the serializer correction. The final serializer was also exercised against real stored reports and archived exports.

## Historical preservation and study limits

The protected container was stopped at entry and at the end of local verification. The protected PostgreSQL volume `opsdesk-lab_opsdesk_postgres` retained its creation time `2026-11-08T12:06:23Z`. The before and after SHA-256 fingerprint of the sorted file paths and contents was `26322a573fe0a3d3666784d745d67085186c08a822b8d39203ed24974108656f`, obtained through a read-only mount. The prior database row counts and logical `docker_probe_01` snapshot digest were not queried again. Historical scorer and renderer reference tests and two archived 2.2.0 exports provide separate reproduction checks. Existing evidence, schema migrations, benchmark specifications and the dataset manifests were preserved.

The [preregistration draft](preregistration-draft.md) is unregistered. The current data support scripted infrastructure validation. They provide no held-out generalization, evidence of live-model reliability, external provider authenticity or causal attribution. Oracle Review remains outside the software release requirements.
