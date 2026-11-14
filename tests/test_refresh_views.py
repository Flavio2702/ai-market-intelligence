import importlib.util
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "refresh_views.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("refresh_views", SCRIPT_PATH)
refresh_views = importlib.util.module_from_spec(spec)
sys.modules["refresh_views"] = refresh_views
spec.loader.exec_module(refresh_views)


def read_views_sql() -> str:
    return (REPO_ROOT / "sql" / "views.sql").read_text(encoding="utf-8")


def extract_view_sql(view_name: str) -> str:
    views = read_views_sql()
    pattern = rf"CREATE OR REPLACE VIEW {re.escape(view_name)} AS\b"
    match = re.search(pattern, views, flags=re.IGNORECASE)
    assert match, f"{view_name} is not defined in sql/views.sql"

    next_view = re.search(
        r"\nCREATE OR REPLACE VIEW\s+",
        views[match.end() :],
        flags=re.IGNORECASE,
    )
    end = match.end() + next_view.start() if next_view else len(views)
    return views[match.start() : end]


class FakeConnection:
    def __init__(self):
        self.executed_sql = []

    def exec_driver_sql(self, sql):
        self.executed_sql.append(sql)


class FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return FakeBegin(self.connection)


def test_refresh_views_reads_views_sql_and_executes_it(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(refresh_views, "get_engine", lambda: FakeEngine(connection))

    views_path = refresh_views.refresh_views()

    assert views_path == REPO_ROOT / "sql" / "views.sql"
    assert len(connection.executed_sql) > 1
    assert any(
        "CREATE OR REPLACE VIEW v_competitor_overview" in statement
        for statement in connection.executed_sql
    )


def test_split_sql_statements_removes_empty_trailing_statement():
    statements = refresh_views.split_sql_statements("SELECT 1;\n\nSELECT 2;\n")

    assert statements == ["SELECT 1", "SELECT 2"]


def test_split_sql_statements_keeps_semicolons_inside_strings():
    statements = refresh_views.split_sql_statements(
        "SELECT 'one;two' AS value;\nSELECT \"semi;colon\" AS name;"
    )

    assert statements == [
        "SELECT 'one;two' AS value",
        'SELECT "semi;colon" AS name',
    ]


def test_views_define_content_asset_validity_layer():
    views = read_views_sql().lower()

    assert "asset_validity_status" in views
    assert "is_valid_content_asset" in views
    assert "validity_reason" in views
    assert "create or replace view v_data_quality_issues" in views


def test_competitor_share_view_separates_crawl_health_from_valid_assets():
    share_sql = extract_view_sql("v_competitor_share_of_voice").lower()

    assert "crawled_ok_pages" in share_sql
    assert "valid_assets" in share_sql
    assert "valid_asset_words" in share_sql
    assert "from raw_pages" in share_sql
    assert "where success = true" in share_sql
    assert "from v_content_asset_validity" in share_sql
    assert "cav.is_valid_content_asset = true" in share_sql
    assert "coalesce(sp.pages_analyzed, 0) as pages_analyzed" in share_sql


def test_competitor_overview_exposes_technical_and_validity_metrics():
    overview_sql = extract_view_sql("v_competitor_overview").lower()

    for field_name in [
        "pages_analyzed",
        "crawled_ok_pages",
        "total_words",
        "share_of_voice",
        "valid_assets",
        "valid_asset_words",
    ]:
        assert f"sov.{field_name}" in overview_sql


def test_content_validity_rejects_low_word_count_successful_pages():
    views = read_views_sql().lower()

    assert re.search(r"word_count\s*<\s*150", views)
    assert "is_valid_content_asset" in views
    assert "low_word_count" in views or "crawl_incomplete" in views


def test_content_validity_rejects_template_or_placeholder_titles():
    views = read_views_sql().lower()

    assert "is_valid_content_asset" in views
    assert (
        "template" in views
        or "placeholder" in views
        or "workhorse - webflow html website template" in views
    )
    assert "template_or_placeholder" in views or "placeholder_title" in views


def test_content_validity_requires_matching_page_insight():
    views = read_views_sql().lower()

    assert "is_valid_content_asset" in views
    assert "page_insights" in views
    assert "missing_insight" in views


def test_best_content_assets_excludes_invalid_assets():
    best_content_assets_sql = extract_view_sql("v_best_content_assets").lower()

    assert "is_valid_content_asset" in best_content_assets_sql
    assert re.search(r"is_valid_content_asset\s*=\s*true", best_content_assets_sql)


def test_content_quality_exposes_explainability_fields():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    for field_name in [
        "freshness_confidence",
        "score_confidence",
        "quality_score",
        "quality_confidence",
        "quality_bucket",
        "quality_evidence_strength",
        "quality_reason",
        "asset_validity_status",
        "is_valid_content_asset",
        "validity_reason",
    ]:
        assert field_name in content_quality_sql


def test_content_quality_unknown_freshness_is_conservative():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "when vpi.freshness_bucket = 'fresh' then 100" in content_quality_sql
    assert "when vpi.freshness_bucket = 'recent' then 75" in content_quality_sql
    assert "when vpi.freshness_bucket = 'old' then 35" in content_quality_sql
    assert "else 20" in content_quality_sql
    assert "when coalesce(pi.freshness_score, 0) > 0 then pi.freshness_score" not in content_quality_sql
    assert "undated_content" in content_quality_sql


def test_content_quality_unknown_freshness_is_page_type_aware():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    dated_match = re.search(
        r"(blog|changelog|release_notes|release notes|updates|news).*?"
        r"freshness_bucket[^\n]*'unknown'.*?then\s+([0-9]+)",
        content_quality_sql,
        flags=re.DOTALL,
    )
    static_match = re.search(
        r"(homepage|pricing|product).*?"
        r"freshness_bucket[^\n]*'unknown'.*?then\s+([0-9]+)",
        content_quality_sql,
        flags=re.DOTALL,
    )

    assert dated_match, (
        "unknown freshness must have an explicit dated-content branch for blogs, "
        "changelogs, release notes, updates, or news"
    )
    assert static_match, (
        "unknown freshness must have an explicit static commercial-page branch "
        "for homepage, pricing, or product pages"
    )
    assert int(dated_match.group(2)) < int(static_match.group(2)), (
        "missing visible dates should penalize dated content more than static "
        "commercial pages"
    )


def test_content_quality_undated_content_warning_is_not_one_flat_quality_penalty():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "undated_content" in content_quality_sql
    assert not re.search(
        r"freshness_bucket[^\n]*'unknown'\s+then\s+20",
        content_quality_sql,
        flags=re.DOTALL,
    ), (
        "undated_content can lower confidence, but unknown freshness must not "
        "force the same flat quality penalty across every source type"
    )


def test_content_quality_excludes_unavailable_freshness_from_active_score_components():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scored_sql = content_quality_sql.split("scored as", 1)[1].split("),\nexplained as", 1)[0]

    assert "freshness_score" in content_quality_sql
    assert "freshness_confidence" in content_quality_sql
    assert "base.depth_score" in scored_sql
    assert "base.proof_score" in scored_sql
    assert "base.structure_score" in scored_sql
    assert "base.clarity_score" in scored_sql
    assert "base.cta_alignment_score" in scored_sql
    assert "base.freshness_score" not in scored_sql, (
        "freshness must remain diagnostic, but unavailable freshness must not "
        "be an active content quality score component"
    )


def test_content_quality_unavailable_freshness_weights_are_renormalized():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scored_sql = content_quality_sql.split("scored as", 1)[1].split("),\nexplained as", 1)[0]

    expected_weights = {
        "base.depth_score": "0.25 / 0.85",
        "base.proof_score": "0.20 / 0.85",
        "base.structure_score": "0.15 / 0.85",
        "base.clarity_score": "0.15 / 0.85",
        "base.cta_alignment_score": "0.10 / 0.85",
    }

    for component, weight in expected_weights.items():
        assert weight in scored_sql and component in scored_sql, (
            "when freshness is unavailable, active quality score weights must "
            f"renormalize the non-freshness weight for {component}"
        )
    assert "0.15 * base.freshness_score" not in scored_sql


def test_asset_score_confidence_is_separate_from_freshness_confidence():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    score_confidence_case = content_quality_sql.split("end as score_confidence", 1)[0].rsplit("case", 1)[1]
    quality_confidence_case = content_quality_sql.split("end as quality_confidence", 1)[0].rsplit("case", 1)[1]

    for confidence_case in [score_confidence_case, quality_confidence_case]:
        assert "freshness_confidence = 'unavailable'" not in confidence_case
        assert "freshness_bucket = 'unknown'" not in confidence_case, (
            "asset score confidence must not automatically become low only "
            "because date/freshness evidence is unavailable"
        )
        assert "depth_score < 35" in confidence_case
        assert "proof_cap_reason is not null" in confidence_case
        assert "cta_cap_reason is not null" in confidence_case


def test_undated_content_warning_does_not_drive_asset_confidence_reason():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    quality_reason_sql = content_quality_sql.split(") as quality_reason", 1)[0].rsplit("concat_ws", 1)[1]

    assert "undated_content" in content_quality_sql
    assert "freshness_confidence" in content_quality_sql
    assert "undated content" not in quality_reason_sql
    assert "unavailable freshness" not in quality_reason_sql
    assert "limiting asset score confidence" not in quality_reason_sql


def test_content_quality_caps_low_depth_without_strong_proof():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "depth_score < 35" in content_quality_sql
    assert "quality_evidence_strength <> 'high'" in content_quality_sql
    assert "least(scored.raw_content_quality_score, 49)" in content_quality_sql
    assert "low_depth" in content_quality_sql
    assert "low_confidence_sample" not in content_quality_sql


def test_classified_proof_elements_view_defines_types_strengths_and_weights():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()

    for proof_type in [
        "testimonial",
        "metric",
        "customer_logo",
        "named_customer",
        "certification",
        "award",
        "case_study",
        "pricing",
        "trial_offer",
        "feature_evidence",
        "generic_claim",
        "unknown",
    ]:
        assert proof_type in proof_sql

    for field_name in [
        "extracted_proof_type",
        "normalized_proof_type",
        "extracted_proof_strength",
        "normalized_proof_strength",
        "proof_normalization_reason",
    ]:
        assert field_name in proof_sql

    for strength in ["high", "medium", "low", "unknown"]:
        assert strength in proof_sql

    assert "then 25" in proof_sql
    assert "then 12" in proof_sql
    assert "then 2" in proof_sql
    assert "else 0" in proof_sql


def test_proof_strength_normalization_downgrades_commercial_and_generic_types():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()

    assert "when typed.normalized_proof_type in ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')" in proof_sql
    assert "then 'low'" in proof_sql
    assert "downgraded commercial or generic proof from extracted high strength" in proof_sql
    assert "commercial or generic proof is low by default" in proof_sql
    assert "when typed.normalized_proof_type in ('metric', 'testimonial', 'case_study', 'certification', 'award')" in proof_sql
    assert "when strength_normalized.normalized_proof_strength = 'high'" in proof_sql


def test_proof_type_normalization_maps_extracted_variants_and_legacy_strings():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()

    assert "when normalized.extracted_proof_type in ('statistic', 'stats', 'statistics')" in proof_sql
    assert "then 'metric'" in proof_sql
    assert "when normalized.extracted_proof_type in ('trial offer', 'trial-offer', 'free trial')" in proof_sql
    assert "then 'trial_offer'" in proof_sql
    assert "feature description" in proof_sql
    assert "statement" in proof_sql
    assert "community feedback" in proof_sql
    assert "else proof_item.proof_element #>> '{}'" in proof_sql


def test_strict_metric_proof_requires_numeric_or_measured_evidence_guard():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()
    metric_branches = []
    current_when = None
    for line in proof_sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("when "):
            current_when = stripped.removeprefix("when ")
        elif current_when is not None and stripped.startswith("then "):
            if stripped == "then 'metric'":
                metric_branches.append(current_when)
            current_when = None
        elif current_when is not None:
            current_when = f"{current_when} {stripped}"

    assert metric_branches, "proof taxonomy should define metric mapping branches"
    for condition in metric_branches:
        assert (
            "proof_evidence_text ~*" in condition
            or "proof_text_normalized ~*" in condition
        ), (
            "metric proof must require evidence text containing a number, count, "
            "percentage, benchmark, time saving, or measured outcome; "
            f"unguarded branch: {condition.strip()}"
        )


def test_strict_proof_taxonomy_keeps_testimonials_and_commercial_claims_separate():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()
    expected_mappings = {
        "customer testimonial": "testimonial",
        "user testimonial": "testimonial",
        "user testimonials": "testimonial",
        "compatibility": "feature_evidence",
        "version requirement": "feature_evidence",
        "version release": "feature_evidence",
        "product capability": "feature_evidence",
        "product capabilities": "feature_evidence",
        "update announcement": "feature_evidence",
        "recognition": "award",
        "trial offer": "trial_offer",
    }

    for extracted_type, normalized_type in expected_mappings.items():
        mapping_pattern = (
            rf"when\s+normalized\.extracted_proof_type\s+in\s*"
            rf"\([^)]*'{re.escape(extracted_type)}'[^)]*\)"
            rf".*?then\s+'{normalized_type}'"
        )
        assert re.search(mapping_pattern, proof_sql, flags=re.DOTALL), (
            f"expected extracted proof type {extracted_type!r} to normalize to "
            f"{normalized_type!r} instead of becoming metric by default"
        )


def test_proof_density_uses_deduplicated_claims_not_raw_mentions():
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()
    proof_density_sql = extract_view_sql("v_proof_density").lower()
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "proof_claim_key" in proof_sql, (
        "classified proof elements should expose a normalized claim key for "
        "duplicate and near-duplicate proof detection"
    )
    for view_name, view_sql in {
        "v_proof_density": proof_density_sql,
        "v_content_quality": content_quality_sql,
    }.items():
        assert (
            "deduplicated_proof_claims" in view_sql
            or re.search(r"count\s*\(\s*distinct\s+[^)]*proof_claim", view_sql)
        ), (
            f"{view_name} must aggregate distinct normalized proof claims, not "
            "raw repeated proof mentions"
        )

    assert "from v_content_quality" in scorecard_sql
    assert "sum(proof_elements_count)" in scorecard_sql
    assert "sum(strong_proof_elements_count)" in scorecard_sql
    assert "sum(weighted_proof_points)" in scorecard_sql
    assert "deduplicated_proof_claims" not in scorecard_sql


def test_low_generic_and_small_sample_proof_cannot_create_strong_validation():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "proof contribution capped: normalized evidence is only low or generic" in content_quality_sql
    assert "proof contribution capped: low/generic normalized evidence is the majority" in content_quality_sql
    assert re.search(
        r"when\s+scored\.valid_assets\s*<\s*3.*?"
        r"(strong_proof_elements_per_valid_asset|weighted_proof_points_per_valid_asset).*?"
        r"(null|0|least)",
        scorecard_sql,
        flags=re.DOTALL,
    ), (
        "small-sample competitors must cap displayed proof validation metrics so "
        "repeated claims on fewer than 3 valid assets cannot look highly validated"
    )


def test_proof_type_mix_view_exposes_breakdown_by_competitor():
    proof_mix_sql = extract_view_sql("v_proof_type_mix_by_competitor").lower()

    for field_name in [
        "competitor_name",
        "proof_type",
        "proof_strength",
        "extracted_proof_type",
        "normalized_proof_type",
        "extracted_proof_strength",
        "normalized_proof_strength",
        "proof_normalization_reason",
        "proof_elements_count",
        "proof_type_share",
    ]:
        assert field_name in proof_mix_sql

    assert "from v_classified_proof_elements" in proof_mix_sql


def test_content_quality_uses_classified_proof_weights_not_stored_score():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "from v_classified_proof_elements" in content_quality_sql
    assert "normalized_proof_strength = 'high'" in content_quality_sql
    assert "normalized_proof_strength = 'medium'" in content_quality_sql
    assert "normalized_proof_strength = 'low'" in content_quality_sql
    assert "normalized_proof_type in ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')" in content_quality_sql
    assert "strong_proof_elements_count" in content_quality_sql
    assert "medium_proof_elements_count" in content_quality_sql
    assert "low_proof_elements_count" in content_quality_sql
    assert "coalesce(pi.proof_score, 0) > 0" not in content_quality_sql
    assert "jsonb_array_length(pi.proof_elements)" not in content_quality_sql
    assert "raw_weighted_proof_score" in content_quality_sql
    assert "proof contribution capped: normalized evidence is only low or generic" in content_quality_sql
    assert "proof contribution capped: low/generic normalized evidence is the majority" in content_quality_sql


def test_content_quality_caps_secondary_only_cta_alignment():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "from v_classified_ctas" in content_quality_sql
    assert "cta_class = 'primary'" in content_quality_sql
    assert "cta_class = 'secondary'" in content_quality_sql
    assert "then least(\n                    45" in content_quality_sql
    assert "cta contribution capped: only secondary ctas were found" in content_quality_sql
    assert "cta_capped" in content_quality_sql


def test_valid_page_insight_base_centralizes_validity_join_for_heavy_views():
    base_sql = extract_view_sql("v_valid_page_insight_base").lower()
    proof_sql = extract_view_sql("v_classified_proof_elements").lower()
    cta_sql = extract_view_sql("v_classified_ctas").lower()
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    assert "join v_content_asset_validity cav on cav.raw_page_id = pi.raw_page_id" in base_sql
    assert "where cav.is_valid_content_asset = true" in base_sql
    assert "from v_valid_page_insight_base" in proof_sql
    assert "from v_valid_page_insight_base" in cta_sql
    assert "from v_valid_page_insight_base" in content_quality_sql


def test_competitor_scorecards_view_exposes_confidence_fields():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    for field_name in [
        "valid_assets",
        "insight_pages",
        "insight_coverage",
        "avg_content_quality_score",
        "avg_content_depth_score",
        "avg_metadata_completeness_score",
        "avg_bofu_strength_score",
        "proof_elements_count",
        "strong_proof_elements_count",
        "weighted_proof_points",
        "proof_elements_per_valid_asset",
        "strong_proof_elements_per_valid_asset",
        "weighted_proof_points_per_valid_asset",
        "score_confidence",
        "confidence_reason",
    ]:
        assert field_name in scorecard_sql


def test_competitor_scorecards_view_exposes_weighted_proof_validation_fields():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    for field_name in [
        "weighted_proof_points_validation_status",
        "weighted_proof_points_validation_reason",
        "weighted_proof_points_max_plausible",
    ]:
        assert field_name in scorecard_sql


def test_competitor_scorecards_weighted_proof_validation_flags_out_of_range_scores():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "weighted_proof_points_per_valid_asset > 100" in scorecard_sql
    assert "out_of_range" in scorecard_sql
    assert "unreliable" in scorecard_sql


def test_competitor_scorecards_weighted_proof_validation_flags_incoherent_zero_strong_proof():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "strong_proof_elements_count = 0" in scorecard_sql
    assert "weighted_proof_points_max_plausible" in scorecard_sql
    assert "weighted_proof_points > weighted_proof_points_max_plausible" in scorecard_sql
    assert "zero strong proof" in scorecard_sql


def test_competitor_scorecards_weighted_proof_validation_keeps_plausible_weak_proof_nonzero():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert not re.search(
        r"strong_proof_elements_count\s*=\s*0.*?"
        r"then\s+0\s+.*?weighted_proof_points_per_valid_asset",
        scorecard_sql,
        flags=re.DOTALL,
    )
    assert "weighted_proof_points_validation_status" in scorecard_sql
    assert "valid" in scorecard_sql


def test_competitor_scorecards_weighted_proof_validation_is_formula_based_not_demo_owned_specific():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    for formula_input in [
        "proof_elements_count",
        "strong_proof_elements_count",
        "weighted_proof_points",
        "valid_assets",
    ]:
        assert formula_input in scorecard_sql

    assert "demo_owned" not in scorecard_sql


def test_competitor_scorecards_use_valid_assets_for_denominators():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "from v_content_asset_validity" in scorecard_sql
    assert "from v_content_quality" in scorecard_sql
    assert "v_classified_proof_elements" not in scorecard_sql
    assert "is_valid_content_asset = true" in scorecard_sql
    assert "validity_reason = 'missing_insight'" in scorecard_sql
    assert "count(*) filter (where is_valid_content_asset = true) as valid_assets" in scorecard_sql
    assert "extraction_eligible_assets" in scorecard_sql
    assert "sa.insight_pages::float / nullif(sa.extraction_eligible_assets, 0)" in scorecard_sql
    assert "qs.proof_elements_count::float / nullif(sa.valid_assets, 0)" in scorecard_sql
    assert "from raw_pages" not in scorecard_sql
    assert "where success = true" not in scorecard_sql


def test_competitor_scorecards_weighted_proof_uses_valid_assets_not_configured_urls():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "configured_urls" not in scorecard_sql, (
        "weighted proof density must not use configured URL counts as its "
        "denominator"
    )
    assert "qs.weighted_proof_points::float / nullif(sa.valid_assets, 0)" in scorecard_sql
    assert "coalesce(qs.weighted_proof_points::float / nullif(sa.valid_assets, 0), 0)" in scorecard_sql


def test_competitor_scorecards_do_not_zero_weighted_proof_for_low_sample_competitors():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()
    final_projection_sql = scorecard_sql.split("scored.weighted_proof_points,", 1)[1]

    assert not re.search(
        r"case\s+when\s+scored\.valid_assets\s*<\s*3.*?"
        r"then\s+0\s+else\s+scored\.weighted_proof_points_per_valid_asset\s+"
        r"end\s+as\s+weighted_proof_points_per_valid_asset",
        final_projection_sql,
        flags=re.DOTALL,
    ), (
        "low sample confidence may be reported separately, but it must not "
        "overwrite weighted_proof_points_per_valid_asset to zero when "
        "recognized proof exists"
    )
    assert "scored.weighted_proof_points_per_valid_asset" in scorecard_sql


def test_competitor_scorecards_include_normalized_proof_weights_in_weighted_points():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "from v_classified_proof_elements" in content_quality_sql
    assert "sum(proof_weight)" in content_quality_sql
    assert "weighted_proof_points" in scorecard_sql
    assert "proof_weight desc" in content_quality_sql
    assert "from v_content_quality" in scorecard_sql


def test_competitor_scorecards_keep_strong_count_distinct_from_weighted_points():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "count(*) filter (where normalized_proof_strength = 'high')" in content_quality_sql
    assert "as strong_proof_elements_count" in scorecard_sql
    assert "coalesce(sum(proof_weight), 0) as raw_weighted_proof_score" in content_quality_sql
    assert "sum(weighted_proof_points)" in scorecard_sql


def test_competitor_scorecards_guard_zero_valid_asset_proof_density():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    for density_formula in [
        "qs.proof_elements_count::float / nullif(sa.valid_assets, 0)",
        "qs.strong_proof_elements_count::float / nullif(sa.valid_assets, 0)",
        "qs.weighted_proof_points::float / nullif(sa.valid_assets, 0)",
    ]:
        assert f"coalesce({density_formula}, 0)" in scorecard_sql


def test_competitor_scorecards_apply_conservative_confidence_thresholds():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()

    assert "when scored.valid_assets < 3 then 'low'" in scorecard_sql
    assert "when scored.insight_coverage < 0.80 then 'low'" in scorecard_sql
    assert "when scored.extraction_eligible_assets >= 5 and scored.insight_coverage >= 0.90 then 'high'" in scorecard_sql
    assert "sample confidence low: fewer than 3 valid assets" in scorecard_sql
    assert "extraction coverage is complete" in scorecard_sql
    assert "sample confidence low: extraction coverage below 80 percent of valid assets" in scorecard_sql
    assert "sample confidence high: 5+ extraction-eligible assets with 90 percent+ extraction coverage" in scorecard_sql
    assert "sample confidence medium: valid assets and extraction coverage are usable but limited" in scorecard_sql


def test_competitor_sample_confidence_is_not_asset_score_confidence():
    scorecard_sql = extract_view_sql("v_competitor_scorecards").lower()
    confidence_case = scorecard_sql.split("end as score_confidence", 1)[0].rsplit("case", 1)[1]
    confidence_reason_case = scorecard_sql.split("end as confidence_reason", 1)[0].rsplit("case", 1)[1]

    for confidence_sql in [confidence_case, confidence_reason_case]:
        assert "valid_assets" in confidence_sql
        assert "insight_coverage" in confidence_sql
        for asset_confidence_term in [
            "freshness_bucket",
            "freshness_confidence",
            "undated_content",
            "quality_confidence",
            "proof_cap_reason",
            "cta_cap_reason",
        ]:
            assert asset_confidence_term not in confidence_sql, (
                "competitor sample confidence must be based on sample size and "
                "extraction coverage, not asset-level score confidence signals"
            )


def test_asset_score_confidence_uses_asset_level_uncertainty_signals():
    content_quality_sql = extract_view_sql("v_content_quality").lower()
    confidence_case = content_quality_sql.split("end as score_confidence", 1)[0].rsplit("case", 1)[1]

    for asset_signal in [
        "depth_score",
        "proof_cap_reason",
        "cta_cap_reason",
        "content_quality_score",
    ]:
        assert asset_signal in confidence_case, (
            "asset score confidence must be based on asset-level evidence quality "
            "and scoring uncertainty"
        )
    assert "freshness_bucket" not in confidence_case


def test_messaging_matrix_uses_separate_aggregation_ctes():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()

    for cte_name in [
        "valid_insights as",
        "insight_page_counts as",
        "messaging_pillars as",
        "value_proposition_themes as",
        "pain_points as",
        "proof_elements as",
        "score_aggregates as",
    ]:
        assert cte_name in messaging_matrix_sql


def test_messaging_matrix_gates_all_page_insight_aggregates_to_valid_assets():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()
    valid_insights_sql = messaging_matrix_sql.split("valid_insights as", 1)[1].split("),\ninsight_page_counts", 1)[0]

    assert "from page_insights pi" in valid_insights_sql
    assert "join v_content_asset_validity cav on cav.raw_page_id = pi.raw_page_id" in valid_insights_sql
    assert "where cav.is_valid_content_asset = true" in valid_insights_sql
    for cte_name in [
        "insight_page_counts",
        "messaging_pillars",
        "value_proposition_themes",
        "proof_elements",
    ]:
        cte_sql = messaging_matrix_sql.split(f"{cte_name} as", 1)[1].split("),\n", 1)[0]
        assert "from valid_insights pi" in cte_sql

    score_aggregates_sql = messaging_matrix_sql.split("score_aggregates as", 1)[1].split(")\nselect", 1)[0]
    assert "from valid_insights pi" in score_aggregates_sql


def test_classified_pain_points_supports_legacy_strings_and_typed_objects():
    pain_sql = extract_view_sql("v_classified_pain_points").lower()

    assert "jsonb_array_elements(coalesce(pi.pain_points" in pain_sql
    assert "jsonb_array_elements_text(coalesce(pi.pain_points" not in pain_sql
    for field_name in [
        "pain_point_text",
        "pain_point_category",
        "pain_point_evidence_type",
        "source_text",
        "source_url",
    ]:
        assert field_name in pain_sql
    for category in [
        "manual work",
        "repetitive workflow",
        "time cost",
        "export/bounce overhead",
        "review friction",
        "sync/versioning",
        "licensing complexity",
        "collaboration bottleneck",
        "approval bottleneck",
    ]:
        assert category in pain_sql
    for evidence_type in ["explicit", "inferred_from_benefit", "keyword_fallback"]:
        assert evidence_type in pain_sql


def test_pain_point_coverage_preserves_legacy_columns_and_exposes_evidence():
    coverage_sql = extract_view_sql("v_pain_point_coverage").lower()

    assert "pain_point_text as pain_point" in coverage_sql
    assert "competitors_mentioning_it" in coverage_sql
    assert "frequency" in coverage_sql
    assert "source_urls" in coverage_sql
    assert "pain_point_categories" in coverage_sql
    assert "pain_point_evidence_types" in coverage_sql
    assert "explicit_frequency" in coverage_sql
    assert "inferred_from_benefit_frequency" in coverage_sql
    assert "keyword_fallback_frequency" in coverage_sql
    assert "from v_classified_pain_points" in coverage_sql


def test_pain_point_coverage_exposes_weighted_evidence_score_ordering():
    coverage_sql = extract_view_sql("v_pain_point_coverage").lower()

    for field_name in [
        "weighted_evidence_score",
        "evidence_strength",
        "evidence_mix",
    ]:
        assert field_name in coverage_sql, (
            "pain point coverage must expose weighted evidence fields so "
            "opportunity logic can distinguish explicit, inferred, and fallback "
            "signals"
        )

    explicit_weight = re.search(
        r"pain_point_evidence_type\s*=\s*'explicit'.*?then\s+([0-9.]+)",
        coverage_sql,
        flags=re.DOTALL,
    )
    inferred_weight = re.search(
        r"pain_point_evidence_type\s*=\s*'inferred_from_benefit'.*?then\s+([0-9.]+)",
        coverage_sql,
        flags=re.DOTALL,
    )
    fallback_weight = re.search(
        r"pain_point_evidence_type\s*=\s*'keyword_fallback'.*?then\s+([0-9.]+)",
        coverage_sql,
        flags=re.DOTALL,
    )

    assert explicit_weight and inferred_weight and fallback_weight, (
        "weighted pain point logic must define explicit, inferred_from_benefit, "
        "and keyword_fallback weights"
    )
    assert float(explicit_weight.group(1)) > float(inferred_weight.group(1))
    assert float(inferred_weight.group(1)) > float(fallback_weight.group(1))


def test_pain_point_coverage_exposes_evidence_mix_counts_for_opportunities():
    coverage_sql = extract_view_sql("v_pain_point_coverage").lower()

    for field_name in [
        "explicit_frequency",
        "inferred_from_benefit_frequency",
        "keyword_fallback_frequency",
        "evidence_mix",
        "dominant_evidence_type",
    ]:
        assert field_name in coverage_sql, (
            "pain point opportunity inputs must make the evidence mix auditable"
        )


def test_messaging_matrix_keeps_legacy_pain_points_and_appends_details():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()

    assert "as pain_points" in messaging_matrix_sql
    assert "pain_point_details" in messaging_matrix_sql
    assert "from v_classified_pain_points" in messaging_matrix_sql
    assert "jsonb_array_elements_text(coalesce(pi.pain_points" not in messaging_matrix_sql


def test_messaging_matrix_counts_distinct_insight_pages():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()

    assert re.search(r"count\s*\(\s*distinct\s+pi\.id\s*\)\s+as\s+insight_pages", messaging_matrix_sql)


def test_messaging_matrix_does_not_cross_product_json_expansions_in_final_select():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()
    final_select_start = messaging_matrix_sql.rfind("\nselect\n    c.id as competitor_id")
    assert final_select_start != -1
    final_select_sql = messaging_matrix_sql[final_select_start:]

    assert "jsonb_array_elements_text" not in final_select_sql
    assert "group by c.id, c.name" not in final_select_sql


def test_messaging_matrix_score_aggregates_use_unexpanded_page_insights():
    messaging_matrix_sql = extract_view_sql("v_messaging_matrix").lower()
    score_aggregates_sql = messaging_matrix_sql.split("score_aggregates as", 1)[1].split(")\nselect", 1)[0]

    assert "from valid_insights pi" in score_aggregates_sql
    assert "jsonb_array_elements_text" not in score_aggregates_sql
    assert "avg(coalesce(pi.genericity_score, 0))" in score_aggregates_sql
    assert "benefit_vs_feature_ratio" in score_aggregates_sql


def test_funnel_mix_uses_valid_assets_for_stage_denominators():
    funnel_sql = extract_view_sql("v_funnel_mix").lower()

    assert "valid_insights as" in funnel_sql
    assert "join v_content_asset_validity cav on cav.raw_page_id = pi.raw_page_id" in funnel_sql
    assert "where cav.is_valid_content_asset = true" in funnel_sql
    assert "from valid_insights" in funnel_sql
    assert "from page_insights\n    group by competitor_id" not in funnel_sql


def test_cta_split_views_are_defined():
    views = read_views_sql().lower()

    assert "create or replace view v_classified_ctas" in views
    assert "create or replace view v_cta_coverage_by_competitor" in views
    assert "create or replace view v_cta_type_mix_by_competitor" in views


def test_classified_ctas_define_legacy_strength_fallbacks():
    classified_ctas_sql = extract_view_sql("v_classified_ctas").lower()

    assert "from v_valid_page_insight_base" in classified_ctas_sql
    assert "explicit_cta_class in ('primary', 'secondary', 'navigation', 'footer', 'unknown')" in classified_ctas_sql
    assert "then 'primary'" in classified_ctas_sql
    assert "book demo|start trial|contact sales|request quote|buy now|sign up|signup|get started|view pricing" in classified_ctas_sql
    assert "free trial|trial|buy|purchase|talk to sales|quote|pricing" not in classified_ctas_sql
    assert "then 'secondary'" in classified_ctas_sql
    assert "learn more|download|watch|guide|docs|documentation|read more" in classified_ctas_sql
    assert "subscribe|tutorial|webinar|view|discover|explore" not in classified_ctas_sql
    assert "then 'navigation'" in classified_ctas_sql
    assert "home|features|blog|resources|about|careers|jobs|login" in classified_ctas_sql
    assert "support|help|menu|navigation" in classified_ctas_sql
    assert "then 'footer'" in classified_ctas_sql
    assert "privacy|terms|cookies|cookie policy|legal|sitemap" in classified_ctas_sql
    assert "then 'unknown'" in classified_ctas_sql
    assert "normalized_cta_type in ('', 'other', 'not_found', 'none', 'unknown')" in classified_ctas_sql


def test_cta_coverage_view_exposes_any_conversion_and_secondary_coverage():
    cta_coverage_sql = extract_view_sql("v_cta_coverage_by_competitor").lower()

    assert "total_insight_pages" in cta_coverage_sql
    assert "total_valid_insight_pages" in cta_coverage_sql
    assert "pages_with_any_cta" in cta_coverage_sql
    assert "any_cta_coverage" in cta_coverage_sql
    assert "pages_with_conversion_cta" in cta_coverage_sql
    assert "conversion_cta_coverage" in cta_coverage_sql
    assert "pages_with_secondary_cta" in cta_coverage_sql
    assert "secondary_cta_coverage" in cta_coverage_sql
    assert "pages_with_cta" in cta_coverage_sql
    assert "cta_coverage" in cta_coverage_sql
    assert "sample_confidence" in cta_coverage_sql
    assert "valid_insights as" in cta_coverage_sql
    assert "v_content_asset_validity" in cta_coverage_sql
    assert "is_valid_content_asset = true" in cta_coverage_sql
    assert "v_classified_ctas" in cta_coverage_sql
    assert "classified.cta_class = 'primary'" in cta_coverage_sql
    assert "classified.cta_class = 'secondary'" in cta_coverage_sql
    assert "classified.cta_class in ('primary', 'secondary', 'navigation', 'footer', 'unknown')" in cta_coverage_sql
    assert "jsonb_array_elements_text" not in cta_coverage_sql
    assert "group by c.id, c.name" in cta_coverage_sql
    assert "group by c.id, c.name, cta_type" not in cta_coverage_sql


def test_conversion_cta_coverage_excludes_secondary_navigation_footer_and_unknown():
    cta_coverage_sql = extract_view_sql("v_cta_coverage_by_competitor").lower()
    conversion_filter = re.search(
        r"where classified\.cta_class = 'primary'\s*\)\s*::float / nullif",
        cta_coverage_sql,
    )

    assert conversion_filter, "conversion coverage must only count primary CTA pages"
    assert "conversion_cta_coverage" in cta_coverage_sql
    assert "where classified.cta_class in ('primary', 'secondary')" not in cta_coverage_sql


def test_topic_saturation_under_three_documents_is_insufficient_data():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    assert re.search(
        r"assets_on_topic\s*<\s*3\s+then\s+'insufficient data'",
        topic_share_sql,
    ) or re.search(
        r"assets_on_topic\s*<=\s*2\s+then\s+'insufficient data'",
        topic_share_sql,
    ), (
        "v_topic_share must map topics with fewer than 3 valid analytical "
        "documents to 'insufficient data' before low, medium, or high branches"
    )
    assert "count(*) < 3 then 'insufficient data'" not in topic_share_sql, (
        "v_topic_share saturation must use topic-level document support, not "
        "the per-competitor grouped row count"
    )
    assert not re.search(r"assets_on_topic\s*<=\s*2\s+then\s+'low'", topic_share_sql)


def test_controlled_topic_saturation_under_three_documents_is_insufficient_data():
    controlled_topic_sql = extract_view_sql("v_controlled_topic_coverage").lower()

    assert re.search(
        r"assets_on_controlled_topic\s*<\s*3\s+.*?then\s+'insufficient data'",
        controlled_topic_sql,
        flags=re.DOTALL,
    ) or re.search(
        r"assets_on_controlled_topic\s*<=\s*2\s+.*?then\s+'insufficient data'",
        controlled_topic_sql,
        flags=re.DOTALL,
    ), (
        "v_controlled_topic_coverage must map controlled topics with fewer "
        "than 3 valid analytical documents to 'insufficient data'"
    )
    assert "count(*) < 3" not in controlled_topic_sql, (
        "v_controlled_topic_coverage saturation must use controlled-topic-level "
        "document support, not the per-competitor grouped row count"
    )
    assert not re.search(
        r"assets_on_controlled_topic\s*<=\s*2\s+.*?then\s+'low'",
        controlled_topic_sql,
        flags=re.DOTALL,
    )


def test_topic_saturation_single_competitor_is_low():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    assert re.search(r"competitors_covering_topic\s*<=\s*1", topic_share_sql), (
        "v_topic_share must have a <= 1 competitor guard for 'low' saturation"
    )
    low_branch = re.search(
        r"when\s+tc\.competitors_covering_topic\s*<=\s*1[^e]",
        topic_share_sql,
    )
    assert low_branch, "competitors_covering_topic <= 1 must appear in a WHEN clause"


def test_topic_saturation_high_threshold_is_4_competitors_or_7_assets():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    assert ">= 4" in topic_share_sql, "high saturation must require >= 4 competitors"
    assert ">= 7" in topic_share_sql, "high saturation must require >= 7 assets"
    assert ">= 10" not in topic_share_sql, (
        "old threshold of >= 10 assets must not appear in v_topic_share"
    )


def test_topic_share_exposes_label_confidence_column():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    assert "label_confidence" in topic_share_sql, (
        "v_topic_share must expose a label_confidence column"
    )
    assert "low confidence" in topic_share_sql, (
        "label_confidence logic must detect the '[low confidence]' label suffix"
    )


def test_topic_share_marks_audited_brand_entity_labels_low_confidence():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    for noisy_label in [
        "bounce / factory / demo aurora",
        "queue / demo boreale / bounce",
        "track / macros / barry",
    ]:
        assert noisy_label in topic_share_sql, (
            "v_topic_share label_confidence must detect audited brand/entity-heavy "
            f"topic label {noisy_label!r}"
        )


def test_topic_gap_exposes_only_strategically_usable_topics():
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()

    assert "label_confidence = 'normal'" in topic_gap_sql, (
        "topic gaps must exclude low-confidence labels before they can become "
        "strategic owned-site gaps"
    )
    assert "topic_saturation <> 'low'" in topic_gap_sql, (
        "topic gaps must exclude low-saturation topics before they can become "
        "strategic owned-site gaps"
    )
    assert "topic_saturation <> 'insufficient data'" in topic_gap_sql, (
        "topic gaps must exclude insufficient-data topics before they can "
        "become strategic owned-site gaps"
    )
    assert "low confidence" in topic_gap_sql, (
        "topic gaps must defensively exclude explicit '[low confidence]' labels"
    )


def test_topic_gap_view_excludes_not_configured_operational_rows():
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()

    assert "not_configured" not in topic_gap_sql
    assert "where oc.has_owned_domain = true" in topic_gap_sql
    assert "and ot.topic_id is null" in topic_gap_sql
    assert "'missing_on_owned_site' as gap_reason" in topic_gap_sql


def test_topic_gap_view_only_exposes_real_owned_site_gaps():
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()

    assert "'covered_by_owned_site'" not in topic_gap_sql
    assert "true as is_gap_vs_own_site" in topic_gap_sql
    assert "false as is_gap_vs_own_site" not in topic_gap_sql


def test_topic_gap_exposes_directional_gap_analysis_status():
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()

    assert "gap_analysis_status" in topic_gap_sql
    assert "directional_only" in topic_gap_sql
    assert "fully_comparable" in topic_gap_sql
    assert "owned domain has low sample confidence" in topic_gap_sql


def test_topic_gap_uses_owned_domain_sample_confidence():
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()

    assert "v_competitor_scorecards" in topic_gap_sql
    assert "is_owned_domain = true" in topic_gap_sql
    assert "score_confidence" in topic_gap_sql
    assert "owned_sample_confidence" in topic_gap_sql


def test_controlled_topic_fields_are_available_for_strategic_topic_outputs():
    schema_sql = (REPO_ROOT / "sql" / "schema.sql").read_text(encoding="utf-8").lower()
    views_sql = read_views_sql().lower()
    combined_sql = f"{schema_sql}\n{views_sql}"

    for field_name in [
        "controlled_topic_id",
        "controlled_topic_label",
        "controlled_topic_confidence",
        "controlled_topic_assignment_reason",
    ]:
        assert field_name in combined_sql, (
            "strategic topic outputs must expose controlled-topic fields "
            f"for {field_name}"
        )


def test_controlled_topic_coverage_is_separate_from_bertopic_diagnostics():
    controlled_topic_sql = extract_view_sql("v_controlled_topic_coverage").lower()

    assert "controlled_topic_id" in controlled_topic_sql
    assert "controlled_topic_label" in controlled_topic_sql
    assert "controlled_topic_confidence" in controlled_topic_sql
    assert "td.topic_label" not in controlled_topic_sql
    assert "v_topic_coverage" not in controlled_topic_sql
    assert "v_topic_share" not in controlled_topic_sql, (
        "controlled strategic topic coverage must not be based on raw "
        "BERTopic concatenated labels"
    )


def test_unknown_other_controlled_topic_stays_low_confidence_and_out_of_gaps():
    controlled_topic_sql = extract_view_sql("v_controlled_topic_coverage").lower()
    controlled_gap_sql = extract_view_sql("v_controlled_topic_gap").lower()

    assert "unknown_other" in controlled_topic_sql
    assert re.search(
        r"unknown_other.*?low",
        controlled_topic_sql,
        flags=re.DOTALL,
    ), "unknown_other must remain low confidence"
    assert "unknown_other" in controlled_gap_sql
    assert re.search(
        r"controlled_topic_id\s*<>\s*'unknown_other'|controlled_topic_id\s*!=\s*'unknown_other'",
        controlled_gap_sql,
    ), "unknown_other must not become an owned-gap opportunity topic"


def test_controlled_topic_gap_keeps_directional_owned_domain_status():
    controlled_gap_sql = extract_view_sql("v_controlled_topic_gap").lower()

    assert "gap_analysis_status" in controlled_gap_sql
    assert "directional_only" in controlled_gap_sql
    assert "owned domain has low sample confidence" in controlled_gap_sql


def test_opportunity_backlog_excludes_not_configured_topic_gaps():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "not_configured" not in opportunity_sql
    assert "where gap_reason = 'missing_on_owned_site'" in opportunity_sql
    assert "where gap_reason in ('not_configured', 'missing_on_owned_site')" not in opportunity_sql


def test_opportunity_backlog_topic_gap_branch_requires_topic_quality_gate():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    topic_gap_cte = opportunity_sql.split("topic_gaps as", 1)[1].split("),\npain_point_opportunities", 1)[0]

    assert "label_confidence = 'normal'" in topic_gap_cte, (
        "topic-derived opportunities must not be built from diagnostic-only "
        "or low-confidence labels"
    )
    assert "topic_saturation <> 'low'" in topic_gap_cte, (
        "topic-derived opportunities must not be built from low-saturation topics"
    )
    assert "topic_saturation <> 'insufficient data'" in topic_gap_cte, (
        "topic-derived opportunities must not be built from insufficient-data topics"
    )
    assert "low confidence" in topic_gap_cte, (
        "topic-derived opportunities must defensively exclude explicit "
        "'[low confidence]' labels"
    )


def test_topic_gap_opportunities_cap_low_owned_sample_confidence():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    topic_gap_select = opportunity_sql.split("from topic_gaps tg", 1)[0].rsplit(
        "union all\nselect", 1
    )[1]

    assert "tg.gap_analysis_status" in opportunity_sql
    assert "directional_only" in topic_gap_select
    assert "least" in topic_gap_select or "then 'medium'" in topic_gap_select
    assert "owned_gap_status" in topic_gap_select


def test_topic_gap_opportunities_never_high_confidence_when_directional():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    topic_gap_select = opportunity_sql.split("from topic_gaps tg", 1)[0].rsplit(
        "union all\nselect", 1
    )[1]

    assert "tg.gap_analysis_status = 'directional_only' then 'medium'" in topic_gap_select
    assert not re.search(
        r"tg\.gap_analysis_status\s*=\s*'directional_only'\s+then\s+'high'",
        topic_gap_select,
    )


def test_topic_gap_opportunities_exclude_owned_domain_from_external_evidence():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    topic_gap_cte = opportunity_sql.split("topic_gaps as", 1)[1].split(
        "),\npain_point_opportunities", 1
    )[0]

    assert "is_owned_domain = false" in topic_gap_cte or "not c.is_owned_domain" in topic_gap_cte


def test_opportunity_backlog_exposes_auditability_fields():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    for field_name in [
        "priority",
        "evidence_strength",
        "competitor_prevalence",
        "funnel_importance",
        "owned_gap_status",
        "gap_analysis_status",
        "gap_analysis_reason",
        "source_count",
        "source_urls",
        "confidence",
        "sample_confidence",
        "recommended_action_type",
        "why_now",
        "blocked_by",
    ]:
        assert field_name in opportunity_sql


def test_opportunity_backlog_exposes_row_contract_for_section_status_derivation():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    for field_name in [
        "owned_gap_status",
        "gap_analysis_status",
        "gap_analysis_reason",
        "blocked_by",
        "source_urls",
        "priority",
        "confidence",
        "sample_confidence",
        "recommended_action_type",
        "related_topic",
    ]:
        assert field_name in opportunity_sql, (
            "Opportunity Backlog section status must be derivable from row "
            f"data; missing row contract field {field_name!r}"
        )

    assert "'not_evaluated_without_owned_gap' as owned_gap_status" in opportunity_sql
    assert "'not_evaluated_without_owned_gap' as gap_analysis_status" in opportunity_sql
    assert "tg.gap_analysis_status" in opportunity_sql
    assert "tg.gap_analysis_reason" in opportunity_sql


def test_opportunity_backlog_requires_real_source_urls():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "'[]'::jsonb as source_urls" not in opportunity_sql
    assert "nullif(url, '') is not null" in opportunity_sql
    assert "where tg.source_count > 0" in opportunity_sql
    assert "jsonb_array_length(coalesce(source_urls, '[]'::jsonb)) > 0" in opportunity_sql


def test_opportunity_backlog_derives_source_count_from_source_urls():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "jsonb_array_elements_text" in opportunity_sql
    assert "count(distinct source_url)" in opportunity_sql
    assert "count(distinct url) as source_count" in opportunity_sql
    assert "jsonb_array_length(coalesce(source_urls, '[]'::jsonb)) as source_count" in opportunity_sql


def test_opportunity_backlog_suppresses_single_weak_pages_as_direct_opportunities():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "quality_gap_clusters" in opportunity_sql
    assert "having count(distinct competitor_id) >= 2" in opportunity_sql
    assert "or count(distinct url) >= 3" in opportunity_sql
    assert "'single_source_quality_signal'" not in opportunity_sql
    assert "'weak_content_quality' as gap_reason" not in opportunity_sql
    assert "'repeated_weak_content_quality' as gap_reason" in opportunity_sql


def test_opportunity_backlog_priority_has_multiple_labels():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "then 'high'" in opportunity_sql
    assert "then 'medium'" in opportunity_sql
    assert "else 'low'" in opportunity_sql
    assert "'medium' as priority" not in opportunity_sql


def test_opportunity_backlog_pain_points_use_weighted_evidence_not_raw_counts_only():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    for field_name in [
        "weighted_evidence_score",
        "evidence_mix",
        "dominant_evidence_type",
        "explicit_frequency",
        "inferred_from_benefit_frequency",
        "keyword_fallback_frequency",
    ]:
        assert field_name in opportunity_sql, (
            "pain-point opportunities must use evidence quality fields, not only "
            "raw source_count or competitor_prevalence"
        )

    pain_branch = opportunity_sql.split("from pain_point_opportunities ppo", 1)[0]
    assert "weighted_evidence_score" in pain_branch
    assert "repeated_competitor_pain_point" in pain_branch


def test_fallback_only_pain_point_opportunities_cannot_be_high_confidence():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "fallback_only" in opportunity_sql, (
        "opportunity logic must explicitly detect fallback-only pain point "
        "patterns before assigning priority or confidence"
    )
    assert re.search(
        r"fallback_only.*?then\s+'low'",
        opportunity_sql,
        flags=re.DOTALL,
    ), (
        "fallback-only pain point opportunities must be capped below high "
        "confidence even when raw mention counts are large"
    )
    assert not re.search(
        r"fallback_only.*?then\s+'high'",
        opportunity_sql,
        flags=re.DOTALL,
    ), "fallback-only pain point evidence must never map directly to high"


def test_fallback_heavy_pain_point_mix_decreases_opportunity_confidence():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "fallback_share" in opportunity_sql, (
        "opportunity logic must calculate fallback share so mostly fallback "
        "evidence can reduce confidence"
    )
    assert re.search(
        r"fallback_share\s*>=\s*0\.[5-9].*?then\s+'low'",
        opportunity_sql,
        flags=re.DOTALL,
    ), (
        "mostly fallback pain point evidence should reduce opportunity "
        "confidence instead of inheriting high confidence from source volume"
    )


def test_medium_pain_point_opportunity_confidence_requires_explicit_or_multiple_inferred_sources():
    coverage_sql = extract_view_sql("v_pain_point_coverage").lower()
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    pain_branch = opportunity_sql.split("from pain_point_opportunities ppo", 1)[0]

    assert (
        "inferred_source_count" in coverage_sql
        or re.search(
            r"count\s*\(\s*distinct\s+source_url\s*\)\s*filter\s*\("
            r"\s*where\s+pain_point_evidence_type\s*=\s*'inferred_from_benefit'",
            coverage_sql,
            flags=re.DOTALL,
        )
    ), (
        "medium confidence from inferred pain must require multiple distinct "
        "inferred sources, not only repeated keyword or weighted-score volume"
    )
    assert "explicit_frequency > 0" in pain_branch or "explicit_frequency >= 1" in pain_branch
    assert "inferred_source_count >= 2" in pain_branch or re.search(
        r"inferred.*source.*>=\s*2",
        pain_branch,
        flags=re.DOTALL,
    )
    assert not re.search(
        r"weighted_evidence_score\s*>=\s*6\s+and\s+ppo\.competitor_prevalence\s*>=\s*2\s+then\s+'medium'",
        pain_branch,
        flags=re.DOTALL,
    ), (
        "weighted evidence score alone must not promote pain-point opportunities "
        "to medium confidence"
    )


def test_pain_point_opportunity_rows_keep_source_urls_visible_with_evidence_mix():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "jsonb_array_length(coalesce(source_urls, '[]'::jsonb)) > 0" in opportunity_sql
    assert "ppo.source_urls" in opportunity_sql
    assert "evidence_mix" in opportunity_sql, (
        "pain point opportunity rows must expose evidence mix alongside source URLs"
    )


def test_cta_type_mix_uses_classified_cta_classes():
    cta_type_mix_sql = extract_view_sql("v_cta_type_mix_by_competitor").lower()

    assert "from v_classified_ctas" in cta_type_mix_sql
    assert "cta_class as cta_type" in cta_type_mix_sql
    assert "cta_type_count" in cta_type_mix_sql
    assert "cta_type_share" in cta_type_mix_sql
    assert "pages_with_cta" not in cta_type_mix_sql
    assert "cta_coverage" not in cta_type_mix_sql


def test_topic_coverage_excludes_invalid_assets_from_main_report_topics():
    topic_coverage_sql = extract_view_sql("v_topic_coverage").lower()

    assert "v_content_asset_validity" in topic_coverage_sql, (
        "v_topic_coverage must join the validity layer so invalid topic documents "
        "cannot feed main report topic diagnostics"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", topic_coverage_sql), (
        "v_topic_coverage must filter to valid analytical assets"
    )


def test_topic_share_excludes_invalid_assets_from_topic_counts():
    topic_share_sql = extract_view_sql("v_topic_share").lower()

    assert "v_content_asset_validity" in topic_share_sql, (
        "v_topic_share must count only valid analytical assets for topic totals "
        "and competitor coverage"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", topic_share_sql), (
        "v_topic_share must filter topic_documents through valid assets"
    )


def test_proof_density_excludes_invalid_assets_from_proof_metrics():
    proof_density_sql = extract_view_sql("v_proof_density").lower()

    assert "v_content_asset_validity" in proof_density_sql, (
        "v_proof_density must use valid assets, not technically successful raw pages, "
        "for proof density denominators and proof counts"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", proof_density_sql), (
        "v_proof_density must filter proof inputs and asset counts to valid assets"
    )
    assert "from raw_pages" not in proof_density_sql, (
        "v_proof_density must not use raw crawl success as its strategic denominator"
    )


def test_classified_pain_points_excludes_invalid_assets_from_strategic_inputs():
    pain_sql = extract_view_sql("v_classified_pain_points").lower()

    assert "v_content_asset_validity" in pain_sql, (
        "v_classified_pain_points must gate page_insights through valid assets "
        "before pain points can feed strategic sections"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", pain_sql), (
        "v_classified_pain_points must exclude placeholder, thin, 404, and "
        "non-evaluable pages"
    )


def test_opportunity_backlog_quality_gaps_use_only_valid_assets():
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()
    quality_gap_sql = opportunity_sql.split("quality_gap_clusters as", 1)[1].split("),\ntopic_gaps as", 1)[0]

    assert "is_valid_content_asset = true" in quality_gap_sql, (
        "quality-gap opportunities must not be created from invalid content-quality rows"
    )
    assert "validity_reason" not in quality_gap_sql or "is_valid_content_asset = true" in quality_gap_sql


def test_best_and_weak_competitor_page_observations_are_valid_only():
    best_sql = extract_view_sql("v_best_content_assets").lower()
    weak_sql = extract_view_sql("v_weak_content_assets").lower()

    assert re.search(r"is_valid_content_asset\s*=\s*true", best_sql), (
        "best competitor page observations must exclude invalid assets"
    )
    assert re.search(r"is_valid_content_asset\s*=\s*true", weak_sql), (
        "weak competitor page observations must exclude invalid assets"
    )


def test_core_and_diagnostic_superset_views_are_defined():
    views = read_views_sql().lower()

    for view_name in [
        "v_core_dataset_reliability",
        "v_core_competitor_scorecards",
        "v_core_content_quality",
        "v_core_funnel_mix",
        "v_core_pain_point_positioning",
        "v_core_proof_evidence",
        "v_core_opportunity_backlog",
        "v_diagnostic_crawl_volume",
        "v_diagnostic_topic_output",
        "v_diagnostic_invalid_assets",
        "v_diagnostic_cta_coverage",
        "v_diagnostic_sentiment",
    ]:
        assert f"create or replace view {view_name}" in views


def test_core_superset_views_do_not_promote_diagnostic_metrics():
    forbidden_core_terms = [
        "share_of_voice",
        "positive_share",
        "negative_share",
        "sentiment_",
        "any_cta_coverage",
        "conversion_cta_coverage",
        "cta_coverage",
        "topic_probability",
        "v_topic_trends",
    ]

    for view_name in [
        "v_core_dataset_reliability",
        "v_core_competitor_scorecards",
        "v_core_content_quality",
        "v_core_funnel_mix",
        "v_core_pain_point_positioning",
        "v_core_proof_evidence",
        "v_core_opportunity_backlog",
    ]:
        view_sql = extract_view_sql(view_name).lower()
        for forbidden_term in forbidden_core_terms:
            assert forbidden_term not in view_sql, (
                f"{view_name} must not promote {forbidden_term} as a core KPI"
            )


def test_core_dataset_reliability_uses_valid_asset_insight_coverage():
    reliability_sql = extract_view_sql("v_core_dataset_reliability").lower()

    assert "from v_content_asset_validity" in reliability_sql
    assert "is_valid_content_asset = true" in reliability_sql
    assert "has_insight = true" in reliability_sql
    assert "extraction_eligible_assets" in reliability_sql
    assert "validity.insight_pages::float / nullif(validity.extraction_eligible_assets, 0)" in reliability_sql
    assert "from page_insights" not in reliability_sql


def test_diagnostic_superset_views_expose_technical_context():
    crawl_sql = extract_view_sql("v_diagnostic_crawl_volume").lower()
    topic_sql = extract_view_sql("v_diagnostic_topic_output").lower()
    invalid_sql = extract_view_sql("v_diagnostic_invalid_assets").lower()
    cta_sql = extract_view_sql("v_diagnostic_cta_coverage").lower()
    sentiment_sql = extract_view_sql("v_diagnostic_sentiment").lower()

    assert "crawled_word_share_proxy" in crawl_sql
    assert "total_words" in crawl_sql
    assert "pages_analyzed" in crawl_sql
    assert "v_topic_trends" in topic_sql
    assert "topic_probability" in topic_sql
    assert "label_confidence" in topic_sql
    assert "v_data_quality_issues" in invalid_sql
    assert "validity_reason" in invalid_sql
    assert "any_cta_coverage" in cta_sql
    assert "conversion_cta_coverage" in cta_sql
    assert "cta_type_share" in cta_sql
    assert "v_competitor_sentiment" in sentiment_sql
    assert "positive_share" in sentiment_sql
    assert "negative_share" in sentiment_sql


def test_view_comments_classify_legacy_weak_metrics_as_diagnostics():
    views = read_views_sql().lower()

    expected_comments = {
        "v_competitor_share_of_voice": "not market share and not strategic kpi",
        "v_competitor_sentiment": "not strategic kpi",
        "v_cta_intelligence": "not strategic kpi",
        "v_topic_trends": "not strategic kpi",
        "v_topic_coverage": "not a core strategic kpi",
        "v_topic_share": "not a core strategic kpi",
    }

    for view_name, expected_phrase in expected_comments.items():
        comment_pattern = (
            rf"comment on view {re.escape(view_name)} is "
            rf"'[^']*{re.escape(expected_phrase)}[^']*'"
        )
        assert re.search(comment_pattern, views), (
            f"{view_name} must be documented as diagnostic or legacy, not as "
            "a strategic KPI"
        )


def test_sentiment_view_documents_controlled_sentiment_values():
    sentiment_sql = extract_view_sql("v_competitor_sentiment").lower()

    for sentiment in ["positive", "negative", "neutral", "mixed", "not_found"]:
        assert f"sentiment = '{sentiment}'" in sentiment_sql, (
            "v_competitor_sentiment must branch only on the documented "
            f"sentiment domain; missing {sentiment}"
        )


def test_funnel_and_topic_gap_views_document_controlled_domains():
    views_sql = read_views_sql().lower()
    funnel_sql = extract_view_sql("v_funnel_mix").lower()
    topic_gap_sql = extract_view_sql("v_topic_gap").lower()
    opportunity_sql = extract_view_sql("v_opportunity_backlog").lower()

    assert "coalesce(pi.funnel_stage, 'unknown')" in funnel_sql
    for funnel_stage in ["'tofu'", "'mofu'", "'bofu'", "'unknown'"]:
        assert funnel_stage in views_sql, (
            "views that branch on funnel_stage must document the allowed "
            f"value {funnel_stage}"
        )

    for topic_saturation in ["'low'", "'medium'", "'high'", "'insufficient data'"]:
        assert topic_saturation in topic_gap_sql or topic_saturation in opportunity_sql, (
            "topic gap and opportunity views must document the view-derived "
            f"topic_saturation value {topic_saturation}"
        )


def test_content_quality_view_documents_freshness_bucket_domain():
    content_quality_sql = extract_view_sql("v_content_quality").lower()

    for freshness_bucket in ["fresh", "recent", "old", "unknown"]:
        assert f"vpi.freshness_bucket = '{freshness_bucket}'" in content_quality_sql, (
            "v_content_quality must branch only on documented freshness_bucket "
            f"values; missing {freshness_bucket}"
        )


def test_controlled_topic_views_document_confidence_and_unknown_other_domains():
    controlled_coverage_sql = extract_view_sql("v_controlled_topic_coverage").lower()
    controlled_gap_sql = extract_view_sql("v_controlled_topic_gap").lower()

    for confidence in ["'low'", "'medium'", "'high'"]:
        assert confidence in controlled_coverage_sql, (
            "v_controlled_topic_coverage must document the controlled topic "
            f"confidence value {confidence}"
        )
    assert "unknown_other" in controlled_coverage_sql
    assert "unknown_other" in controlled_gap_sql
    assert "controlled_topic_id <> 'unknown_other'" in controlled_gap_sql


def test_superset_docs_separate_core_kpi_views_from_diagnostics():
    docs = (REPO_ROOT / "docs" / "superset_setup.md").read_text(encoding="utf-8")
    lower_docs = docs.lower()

    assert "recommended core kpi views:" in lower_docs
    assert "diagnostics and debug views:" in lower_docs
    assert "legacy compatibility views" in lower_docs

    core_block = lower_docs.split("recommended core kpi views:", 1)[1].split(
        "diagnostics and debug views:", 1
    )[0]
    diagnostic_block = lower_docs.split("diagnostics and debug views:", 1)[1].split(
        "legacy compatibility views", 1
    )[0]

    for view_name in [
        "v_core_dataset_reliability",
        "v_core_competitor_scorecards",
        "v_core_content_quality",
        "v_core_funnel_mix",
        "v_core_pain_point_positioning",
        "v_core_proof_evidence",
        "v_core_opportunity_backlog",
    ]:
        assert view_name in core_block

    for diagnostic_view in [
        "v_diagnostic_crawl_volume",
        "v_diagnostic_topic_output",
        "v_diagnostic_invalid_assets",
        "v_diagnostic_cta_coverage",
        "v_diagnostic_sentiment",
    ]:
        assert diagnostic_view in diagnostic_block

    for weak_metric_view in [
        "v_competitor_share_of_voice",
        "v_competitor_sentiment",
        "v_cta_intelligence",
        "v_topic_trends",
    ]:
        assert weak_metric_view not in core_block

    assert "generic cta coverage is not a core kpi" in lower_docs
    assert "topic output is diagnostic" in lower_docs


def test_readme_describes_core_and_diagnostic_superset_views():
    readme = (REPO_ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8").lower()

    assert "`v_core_*` datasets for decision-useful kpi" in readme
    assert "`v_diagnostic_*` datasets" in readme
    assert "legacy view names remain available" in readme
    assert "are diagnostics, not strategic kpi" in readme
