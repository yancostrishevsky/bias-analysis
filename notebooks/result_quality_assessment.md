# Result Quality Assessment

## 1. Executive Verdict

The results are useful for a master's thesis, but not all parts are equally strong.

The strongest thesis evidence is:

- Query sensitivity: bias-triggering variants often produced very different result sets from baselines.
- Metadata and enrichment quality: the tool can expose bibliographic quality differences across LLMs and scholarly providers.
- LLM versus scholarly provider overlap: overlap is extremely low, which is a meaningful and thesis-relevant result.
- Language-query behavior: target-language wording visibly changes language metadata in several runs, but claims need caveats.
- Open access/preprint shift for recency-style queries: useful as a secondary result.

The weaker evidence is:

- Venue/publisher/prestige bias: the metrics are readable after cleanup, but the measured deltas are small and inconsistent.
- Citation/popularity bias: citation counts are not central enough in the exported summaries, so the current evidence is mostly proxy-based.
- Geographic bias: some shifts are visible, especially China, but Africa results mix direct metadata and heuristics; some figures are still visually weak.
- Hallucination risk: useful for bibliographic risk discussion, but risky to frame as "hallucination" without explaining that it is mostly canonical-match/enrichment risk.

Overall, the experiment output is good enough for a thesis evaluation chapter if presented as exploratory evidence from a tool, not as definitive behavioral claims about all AI literature search. More experiments are not strictly required for a master's thesis, but repeating the most important runs with fewer selected models and clearer metadata validation would improve the evidence substantially.

## 2. Data Coverage

The notebook loaded 8 runs:

- 1 completed scholarly/provider run with 20 queries and 729 records.
- 1 partial core LLM audit run with 20 queries and 1,308 records.
- 6 additional partial LLM audit runs for venue, citation/popularity, and language experiments, with 384-421 records each.

The exported workflow loaded 4,444 raw records and mapped them to 5,466 experiment rows. The mapped row count is larger because some queries belong to multiple experiment sets. There are 290 pairwise comparisons and all 50 expected configured queries were matched.

This is enough for a thesis discussion, but not perfectly balanced:

- LLM results dominate the dataset.
- The scholarly provider comparison exists mainly for Set A/core queries, not for all additional B/C/D runs.
- Most LLM runs are marked `partial`, so failed calls and missing model outputs must be acknowledged.
- Some systems contribute more records than others; OpenAI has 665 LLM records while Claude has 420 and DeepSeek has 418.
- The dataset is suitable for exploratory analysis, but not for strong statistical generalization.

Verdict: usable, but describe it as an exploratory evaluation over completed runs with partial-run caveats.

## 3. Query Sensitivity Results

This is one of the strongest findings.

Pairwise result-set overlap is low:

- Mean Jaccard similarity: 0.119.
- Median Jaccard similarity: 0.0.
- Mean top-K overlap: 0.169.
- Median top-K overlap: 0.0.

For Set A, the median Jaccard and top-K overlap are both 0.0. This indicates that, for many model/provider/pair combinations, the baseline and variant queries returned almost entirely different records.

The result is meaningful because it directly answers a core thesis question: wording changes in AI-based literature search can substantially change what appears in the result set.

Use in thesis:

- Include `fig_core_jaccard_by_model_provider.png`.
- Include `fig_core_topk_overlap_by_model_provider.png`.
- Support them with `table_pairwise_comparison_summary.csv`.

Safe claim:

> Bias-triggering query variants frequently changed result sets compared with baseline queries, especially in top-ranked records.

Avoid overclaiming:

> Do not claim this proves bias by itself. Low overlap shows sensitivity to wording, not necessarily unfairness or systematic bias.

## 4. Temporal / Recency Results

The temporal evidence is moderate.

The global publication-year delta has extreme outliers:

- Mean delta: -5.45 years.
- Median delta: +0.23 years.
- Minimum: -2014 years.
- Maximum: +34.57 years.

The mean is distorted by bad or missing year values, so the median is more trustworthy. The Set A median shift is +0.875 years and Set D is +0.778 years. For open-access/recency pairs, recent-5-year share increased for A03 (+0.271 median) and A06 (+0.155 median).

Use in thesis:

- Use `fig_publication_year_shift.png` only with a note that outliers exist.
- Prefer median summaries in the text.
- Discuss recency shift as suggestive, not definitive.

Safe claim:

> Some query variants, especially recency-style variants, suggest a shift toward newer records based on available publication-year metadata.

Avoid overclaiming:

> Do not claim all "latest" queries reliably return newer literature. The year delta distribution contains serious outliers and should be cleaned or winsorized for stronger evidence.

## 5. Venue / Publisher / Prestige Results

The improved figures are much better than the original overloaded chart, but the substantive evidence is weak to moderate.

The median deltas are small for most venue/publisher pairs:

- A05 / B01 top venue share delta: 0.000.
- B02 top venue share delta: 0.000.
- B03 top venue share delta: +0.042.
- B04 top venue share delta: +0.025.
- B05 top venue share delta: -0.069.
- B06 top venue share delta: 0.000.

Publisher concentration shifts are somewhat more visible in places, e.g. C02 publisher share delta +0.133, but still proxy-based.

Visual quality:

- `fig_venue_concentration.png`: now readable enough as a diagnostic aggregate chart.
- `fig_venue_concentration_by_bias_type.png`: better for thesis than the raw chart.
- `fig_venue_concentration_delta.png`: conceptually useful, but has some y-label collision around top GPT-5.4 rows. Use after small cleanup or as supplementary.
- `fig_venue_concentration_top_models.png`: useful for diagnosing cases, less useful as a main thesis figure.
- `fig_publisher_concentration_delta.png`: useful but should be treated as proxy evidence.

Use in thesis:

- Include venue/publisher concentration only as a secondary analysis.
- Prefer delta charts over raw concentration charts.
- Explain that this is a proxy for prestige/publisher bias, not a direct venue-rank measurement.

Safe claim:

> Prestige-oriented wording changed venue or publisher concentration for some systems, but the effect is inconsistent.

Avoid overclaiming:

> Do not claim prestige wording systematically increases top-venue concentration across all models/providers.

## 6. Citation / Popularity Results

This is currently weak.

The experiment design is good, but the exported result quality does not yet support strong citation/popularity claims. Citation counts exist in some enriched records, but the main exported summaries emphasize overlap, venue concentration, publisher concentration, and metadata proxies rather than direct citation-count distributions.

The C-set pairwise overlap is higher than Set A:

- Set C median Jaccard: 0.160.
- Set C median top-K overlap: 0.286.
- Set C median publication-year delta: -0.550.

That suggests popularity wording may pull toward more canonical/older results, but this is not enough without stronger citation-count analysis.

Use in thesis:

- Use only as supplementary or exploratory.
- If included, say "proxy indicators" clearly.

Safe claim:

> Popularity-oriented wording shows some changes in overlap and concentration proxies, but citation-count evidence is not strong enough for a primary claim.

Avoid overclaiming:

> Do not claim that "best", "important", or "landmark" reliably increases citation impact unless citation-count distributions are explicitly analyzed and shown.

Recommended improvement:

- Add a direct citation-count delta table and boxplot/histogram for C01-C06.
- Separate records with missing citation counts from records with zero citations.

## 7. Language Results

Language results are meaningful, but require caveats.

The target-language deltas are positive:

- Polish: +0.385.
- Spanish: +0.611.
- French: +0.729.
- German: +0.474.
- Portuguese: +0.811.
- Arabic: +0.638.

This is a useful result: language-specific wording does often shift results toward target-language metadata.

However, English remains common in variants:

- Polish variant still averages 0.862 English share.
- French variant still averages 0.850 English share.
- Arabic variant has missing language share in some systems.

This is actually thesis-relevant: language-targeted queries can increase target-language records while still returning many English records.

Visual quality:

- `fig_language_target_delta.png` is readable and useful.
- `fig_language_shift.png` is more detailed and may be too busy for the main thesis; use as supplementary.

Safe claim:

> Language-specific queries increased target-language metadata shares in several pairs, but did not eliminate English-language dominance.

Avoid overclaiming:

> Do not claim the systems correctly satisfy language constraints. The output still contains many English records and language metadata may be missing or provider-derived.

## 8. Geographic Results

Geographic results are mixed.

China/regulation is stronger than Africa/healthcare:

- A08 variant has high China share in many systems.
- Several A08 deltas are large, including +1.0 for some systems/providers.

Africa/healthcare is weaker:

- A01 variant introduces Africa metadata/heuristic buckets in some systems.
- But the result mixes direct country metadata and title/venue heuristics.
- The chart `fig_geographic_shift_africa.png` is crowded but readable enough for diagnosis.
- `fig_geographic_africa_delta.png` has clipped y-axis labels and should not be used as-is in the thesis.

The country metadata is present often enough to explore, but geographic interpretation remains fragile because country can mean author affiliation, publisher country, venue country, or inferred topical geography depending on the record.

Use in thesis:

- Use China/regulation as moderate evidence.
- Use Africa/healthcare cautiously and separate direct metadata from heuristic indicators.

Safe claim:

> Geographic query variants changed available country/geographic indicators, especially for China-related regulation queries.

Avoid overclaiming:

> Do not claim the Africa query objectively shifted author geography or regional representation unless country-field provenance is checked record by record.

Recommended improvement:

- Regenerate Africa delta with shorter labels or aggregate by source type.
- Separate direct metadata buckets from heuristic buckets in different charts.

## 9. Open Access / Preprint Results

This is a useful secondary result.

For A03 (information retrieval vs latest neural information retrieval):

- Median open-access share delta: +0.295.
- Median preprint share delta: +0.243.
- Median recent-5-year share delta: +0.271.

For A06 (large language models vs latest research on large language models):

- Median open-access share delta: 0.000.
- Median preprint share delta: 0.000.
- Median recent-5-year share delta: +0.155.

This suggests the recency framing has some effect, but it is query-dependent.

Visual quality:

- `fig_open_access_preprint_delta.png` is readable.
- `fig_open_access_preprint_shift.png` is less thesis-friendly than the delta chart.

Safe claim:

> Recency-style wording may increase preprint/open-access or recent-publication indicators for some query pairs.

Avoid overclaiming:

> Do not claim "latest research" consistently increases preprint or open-access results.

## 10. Metadata Completeness and Enrichment Quality

This is one of the strongest and most thesis-relevant sections.

Average metadata completeness is high:

- LLM records: 0.966.
- Scholarly provider records: 0.930.

But enrichment/canonical matching differs sharply:

- LLM high-risk share: 0.503.
- LLM canonical match rate: 0.497.
- Scholarly provider high-risk share: 0.000.
- Scholarly provider canonical match rate: 1.000.

This is important because it shows why the tool is useful: it does not only collect results, it makes bibliographic quality inspectable.

However, be careful: the LLM metadata completeness is high because LLMs often provide structured-looking metadata. That does not mean the metadata is correct. The high risk/canonical mismatch rate is the more important quality signal.

Use in thesis:

- Include `fig_metadata_completeness_heatmap.png` for overview.
- Include `fig_metadata_completeness_delta.png` only as secondary; deltas are mostly small.
- Include model/provider ranking cautiously; the ranking formula is composite and should not be overemphasized.

Safe claim:

> The tool exposes a difference between apparent metadata completeness and bibliographic verifiability.

Avoid overclaiming:

> Do not say LLMs have better metadata quality than providers just because their fields are more populated.

## 11. Hallucination / Bibliographic Risk

This is meaningful but must be framed carefully.

The LLM high-risk share is about 0.503, while scholarly providers are 0.000 by construction of the enrichment/canonical matching logic. This is a strong signal that LLM-generated records need verification.

But A10 does not behave as expected:

- A10 LLM baseline high-risk share: 0.446.
- A10 LLM variant high-risk share: 0.277.

The hallucinated-DOI niche variant did not clearly increase risk; it appears to reduce risk on average. That means the A10 result should not be used to claim niche hallucination queries increase hallucination risk.

Visual quality:

- `fig_hallucination_risk_delta.png` is readable and useful, but it shows mixed directions.
- `fig_hallucination_risk_by_bias_type.png` is useful as an overview.

Safe claim:

> LLM-generated literature records show substantial bibliographic verification risk compared with scholarly provider records.

Avoid overclaiming:

> Do not claim high-risk records are necessarily fake.
> Do not claim the niche hallucination query increased risk; the exported data does not support that.

## 12. LLM vs Scholarly Provider Comparison

This is a strong thesis result, but it is negative evidence.

LLM-provider overlap is extremely low:

- Mean Jaccard: 0.0013.
- Median Jaccard: 0.0000.
- Maximum Jaccard: 0.1333.
- OpenAlex is the closest provider on average, but still only 0.0051.
- Scopus and Semantic Scholar average 0.0000 overlap.

This strongly suggests that LLM-generated literature lists do not resemble provider result sets for the same queries, at least under the current identity matching.

Visual quality:

- `fig_llm_provider_overlap_heatmap.png` is readable.
- The heatmap is visually sparse because nearly all values are zero; that is the result, not a plotting failure.

Safe claim:

> LLM-generated literature lists have very low overlap with scholarly provider search results for the same queries.

Avoid overclaiming:

> Do not claim providers are ground truth.
> Do not claim LLM outputs are wrong solely because overlap is low.
> Mention DOI/title matching and provider coverage limitations.

## 13. Visual Quality Review

Recommended as main thesis figures:

- `fig_core_jaccard_by_model_provider.png`: use as-is.
- `fig_core_topk_overlap_by_model_provider.png`: use as-is.
- `fig_llm_provider_overlap_heatmap.png`: use as-is, with explanation that near-zero overlap is the finding.
- `fig_metadata_completeness_heatmap.png`: use as-is or after small title/label cleanup.
- `fig_language_target_delta.png`: use as-is, but explain language metadata caveats.
- `fig_open_access_preprint_delta.png`: use as-is as secondary evidence.

Use after small cleanup:

- `fig_venue_concentration_delta.png`: useful, but one or more labels overlap.
- `fig_publisher_concentration_delta.png`: useful as proxy evidence.
- `fig_hallucination_risk_delta.png`: readable, but interpret carefully because deltas are mixed.
- `fig_publication_year_shift.png`: useful, but outliers need discussion.

Regenerate differently:

- `fig_geographic_africa_delta.png`: y-axis labels are clipped; aggregate by source type or shorten buckets.
- `fig_geographic_shift_africa.png`: too many rows for a main thesis figure.
- `fig_language_shift.png`: too detailed for main thesis figure; use selected aggregate instead.

Discard or keep only as diagnostics:

- `fig_venue_concentration_top_models.png`: useful for debugging, not main thesis argument.
- `fig_model_provider_summary_ranking.png`: composite ranking is too subjective for a primary thesis claim.
- `fig_provider_coverage_by_query.png`: useful diagnostic, weak thesis figure.

The automated `table_recommended_thesis_figures.csv` is too optimistic because it recommends every candidate figure. Human assessment should override it.

## 14. Claims That Can Be Safely Made

Strong:

1. Bias-triggering query variants often changed result sets substantially compared with baseline queries.
2. Top-ranked records are highly sensitive to query wording in many pairs.
3. LLM-generated literature lists have extremely low overlap with scholarly provider result sets.
4. The tool exposes a useful distinction between metadata completeness and bibliographic verifiability.
5. LLM-generated records require canonical verification; many do not match enrichment sources.

Moderate:

1. Language-specific wording increases target-language metadata shares in several experiments, while English records remain common.
2. Recency-style wording may increase recent/preprint/open-access indicators for some pairs.
3. Geographic wording changes country/geographic indicators, especially for China-related regulation queries.

Weak:

1. Prestige wording systematically increases top-venue concentration.
2. Popularity wording systematically retrieves more cited or canonical literature.
3. Africa-specific query framing improves representation of African scholarship.
4. Niche hallucination-related queries increase bibliographic risk.

## 15. Claims That Would Be Overclaiming

Do not claim:

- The experiments prove that specific models are biased in a general sense.
- High-risk LLM records are confirmed hallucinations.
- Provider records are perfect ground truth.
- Country metadata directly measures author geography or regional representation without provenance checks.
- Language-specific queries reliably satisfy language constraints.
- Prestige/popularity wording reliably increases citation impact.
- The model/provider ranking is an objective quality ranking.

## 16. Recommended Repeats or Improvements

Highest priority:

1. Repeat the core Set A with fewer models and all calls completed, so the comparison is balanced.
2. For citation/popularity experiments, add direct citation-count distribution plots and missing-citation diagnostics.
3. For geographic experiments, split direct country metadata from heuristic geographic indicators.
4. For hallucination risk, manually audit a small sample of high-risk and low-risk LLM records to validate the risk label.

Medium priority:

1. Regenerate Africa geographic figures with shorter labels and aggregation by source type.
2. Winsorize or clean impossible publication-year deltas before using temporal charts.
3. Report medians and interquartile ranges, not only means.
4. Add per-query sample-size annotations for selected figures.

Not necessary for thesis completion, but useful:

1. Repeat Scholarity/provider runs for Sets B, C, and D, not only Set A.
2. Add statistical uncertainty intervals if the chapter needs stronger empirical framing.

## 17. Final Assessment

The results are not poor evidence, but they are uneven. They are good enough for a master's thesis chapter if framed as an evaluation of a tool that helps inspect and compare bias-related signals, not as a definitive benchmark of model bias.

The thesis should emphasize:

- query sensitivity,
- bibliographic verification risk,
- metadata/enrichment inspectability,
- LLM-provider divergence,
- and selected language/recency shifts.

The thesis should de-emphasize:

- citation/popularity claims,
- broad geographic representation claims,
- model ranking,
- and prestige-bias conclusions unless presented as proxy-based exploratory findings.
