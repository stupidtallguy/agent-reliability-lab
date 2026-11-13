# Preregistration draft for an OpsDesk defense study

**Status** — Draft for planning. No approval, registration, held-out data, or live-model authorization exists for this draft. The scripted demonstration is prior development work.

## Questions and hypotheses

1. How does the guarded configuration change the probability of a verified attacker outcome relative to the baseline under the same task, tool permissions, and injection plan?
2. How does it change legitimate task completion, including cases with no attack?
3. How does it change recovery after a recoverable fault, unauthorized attempts, prohibited effects, defensive blocks on benign tasks, and evidence coverage?

The directional primary hypothesis is a lower attack success rate under guarded execution. The corresponding difference is guarded minus baseline, with zero as the null. Task success on benign trials is a secondary outcome for possible defense costs. A task-success noninferiority claim would require a justified margin and an approved decision rule before collection.

## Conditions and experimental unit

Compare the implemented `baseline` and `guarded` configurations with identical trusted actor, permissions, initial fixture, scenario and input, injection or fault plan, model settings, budgets, and transport. Freeze the exact dataset, scenario, oracle rules, scorer implementation, lock, and execution source hashes. Identify each experimental unit by its unique baseline and guarded trial and execution references. Match on scenario and planned repeat before examining outcomes. Group repeated units by template family for uncertainty estimates. Keep development, scripted demonstration, and any independently authored held-out data separate.

Use the development catalog and scripted model for infrastructure validation. A model ID, provider settings, schedules, budgets and an execution authorization for a future model study remain to be specified. The held-out partition is empty. A future protocol must record execution order, infrastructure conditions and any blocking or randomization procedure before data collection.

## Outcomes and denominators

- Primary attack outcome is the difference in verified attacker success across matched, exposed, determinate units. Report condition-specific ASR as `S/K` and paired risk difference separately. An objective contradiction vetoes a trial-level determination. This conditional contrast is subject to selection when the defense changes exposure or evidence availability.
- Report coverage `K/(A-U)`, unknown exposure, unknown outcomes and verified completed unexposed controls by condition. Keep all planned slots in the population accounting.
- Secondary outcomes are objective task success, recovery among verified exposed recoverable-fault trials, unauthorized proposals with complete proposal evidence, prohibited effects with complete reconciliation, and defense blocks among assessable benign guarded controls. Report latency and cost descriptively where observations are available.
- Keep attack attempts and committed effects separate. Temporal eligibility alone cannot establish causal influence from the payload.

## Sample size and analysis plan

The seven demo pairs and the 38 development scenarios are engineering fixtures. Neither supplies a confirmatory sample size. Before registration, specify the primary target population, expected number of independent families, within-family repeats, practically important difference, plausible discordance, anticipated missingness and a resulting sample-size rationale. A fixed stopping rule and any multiplicity or significance policy remain open. Do not stop based on observed benefit.

Report paired risk differences, discordant counts, family counts, and a family-bootstrap interval when the number of families supports meaningful resampling. Pin the bootstrap seed, draws and interval level at registration. An exact McNemar calculation assumes independent paired discordances for its inferential interpretation. Treat it descriptively when repeated units within families violate that assumption. Report Wilson intervals for marginal proportions as descriptive summaries alongside denominators. Avoid superiority claims from small or clustered engineering samples.

## Exclusions, missing data, and sensitivity

Retain every planned slot. Exclude pair aliases, reused trial or execution identities, incompatible scorer/oracle rules, and comparisons that fail scenario or condition equivalence from verified paired estimates. Record reasons. Report infrastructure failure, unmaterialized runs, interruption, unexposed control, unknown exposure, and unknown outcome separately. Keep unknown outcomes out of measured success and failure counts. Use `null` for ASR with zero determinate outcomes.

Report paired complete-case results alongside worst/best-case bounds that assign eligible unresolved outcomes to each endpoint. Report how estimates change if a family is left out or if missingness differs by condition. Keep a separate accounting for structural ineligibility, such as an attack metric in a benign scenario. Document deviations as append-only amendments. See [statistical methodology](statistical-methodology.md) and [metric definitions](metrics-definitions.md).

## Registration

Before collecting confirmatory data, fill the open parameters, authorize and freeze the design, and pin the dataset and scoring references through the [registration workflow](preregistration.md). This draft remains unregistered.
