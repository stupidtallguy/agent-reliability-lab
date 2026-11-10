# Statistical methodology

The verified experimental unit is one distinct baseline/guarded trial pair with
unique execution identities. Aliases and reuse of either side are rejected. Distinct
repeated trials remain separate observations within their declared template family;
they are not automatically independent samples. Repeated-measures weighting is not
implemented. Anonymous arithmetic is explicitly unverified descriptive output.

Analysis pins dataset release, scenario, seed/input/conditions, oracle rules,
evaluator implementation and exact score revisions. Changing scoring rules cannot
be interpreted as improved agent performance. Explicit cross-version comparisons
remain separate labeled cohorts with separate denominators.

Reported estimands include guarded-minus-baseline risk differences for objective
task success, attack success, exposed recoverable faults, unauthorized attempts,
prohibited effects and benign defensive blocks. Cases outside a metric's scope are
not applicable, not unknown. In-scope missing outcomes remain unknown/excluded and
are reflected in complete-pair coverage and worst-case missing-pair bounds.

Family-aware bootstrap resamples equal-weight template-family mean differences
with a recorded seed and resample count. The percentile 95% interval requires at
least two represented families and warns below 20. Unequal family sizes distinguish
family-weighted and trial-weighted estimands. The demo deliberately has insufficient
families for a useful family interval. Wilson success intervals are descriptive;
repeated trials do not establish independent Bernoulli observations.

Exact two-sided McNemar uses min(1,2*P[Binomial(b+c,0.5)<=min(b,c)]), with discordant
pairs b,c. Inferential p-values require an explicit independent-unit justification,
complete pairs and one family per pair. Otherwise p is unavailable. Empty or fully
unknown samples produce null rates, not zero performance. No significance claim
is made for the synthetic demo.

ASR and coverage are defined in evaluator-1.7.md. Cost requires known provider usage
and a versioned exact-model price with effective date/provenance; scripted tokens and
cost are not live spending. Latency uses measured execution duration, not synthetic
fixture time; p95 uses the documented existing quantile method and sample warnings.
Preregistration should pin estimands, sample-size rationale, exclusions, sensitivity
analyses and methods before authorized data collection.
