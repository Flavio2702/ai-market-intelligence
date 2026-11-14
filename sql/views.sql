CREATE OR REPLACE VIEW v_content_asset_validity AS
WITH page_base AS (
    SELECT
        rp.id AS raw_page_id,
        rp.competitor_id,
        c.name AS competitor_name,
        rp.url,
        COALESCE(su.source_type, rp.asset_type, 'other') AS source_type,
        COALESCE(rp.asset_type, su.source_type, 'other') AS asset_type,
        COALESCE(rp.title, '') AS title,
        COALESCE(rp.word_count, 0) AS word_count,
        rp.success,
        COALESCE(length(btrim(rp.markdown)), 0) AS markdown_length,
        EXISTS (
            SELECT 1
            FROM page_insights pi
            WHERE pi.raw_page_id = rp.id
        ) AS has_insight,
        lower(COALESCE(rp.title, '')) AS normalized_title
    FROM raw_pages rp
    JOIN competitors c ON c.id = rp.competitor_id
    LEFT JOIN source_urls su ON su.id = rp.source_url_id
),
classified AS (
    SELECT
        raw_page_id,
        competitor_id,
        competitor_name,
        url,
        source_type,
        asset_type,
        title,
        word_count,
        has_insight,
        CASE
            WHEN success = FALSE THEN 'invalid'
            WHEN markdown_length < 50 THEN 'invalid'
            WHEN word_count < 150 THEN 'invalid'
            WHEN has_insight = FALSE THEN 'invalid'
            WHEN position('template' in normalized_title) > 0
              OR position('placeholder' in normalized_title) > 0
              OR position('webflow html website template' in normalized_title) > 0
              OR position('error' in normalized_title) > 0
              OR position('404' in normalized_title) > 0
              OR position('not found' in normalized_title) > 0
              OR position('unavailable' in normalized_title) > 0
              OR position('forbidden' in normalized_title) > 0
              OR position('access denied' in normalized_title) > 0
              OR position('incomplete' in normalized_title) > 0 THEN 'invalid'
            ELSE 'valid'
        END AS asset_validity_status,
        CASE
            WHEN success = FALSE THEN 'crawl_failed'
            WHEN markdown_length < 50 THEN 'empty_markdown'
            WHEN word_count < 150 THEN 'low_word_count'
            WHEN has_insight = FALSE THEN 'missing_insight'
            WHEN position('template' in normalized_title) > 0
              OR position('placeholder' in normalized_title) > 0
              OR position('webflow html website template' in normalized_title) > 0
              OR position('error' in normalized_title) > 0
              OR position('404' in normalized_title) > 0
              OR position('not found' in normalized_title) > 0
              OR position('unavailable' in normalized_title) > 0
              OR position('forbidden' in normalized_title) > 0
              OR position('access denied' in normalized_title) > 0
              OR position('incomplete' in normalized_title) > 0 THEN 'template_or_placeholder'
            ELSE 'valid'
        END AS validity_reason
    FROM page_base
)
SELECT
    raw_page_id,
    competitor_id,
    competitor_name,
    url,
    source_type,
    title,
    word_count,
    has_insight,
    asset_validity_status,
    asset_validity_status = 'valid' AS is_valid_content_asset,
    validity_reason
FROM classified;

CREATE OR REPLACE VIEW v_competitor_share_of_voice AS
WITH successful_pages AS (
    SELECT
        competitor_id,
        COUNT(*) AS pages_analyzed,
        COALESCE(SUM(COALESCE(word_count, 0)), 0) AS total_words
    FROM raw_pages
    WHERE success = TRUE
    GROUP BY competitor_id
),
total_words_all AS (
    SELECT COALESCE(SUM(total_words), 0) AS total_words
    FROM successful_pages
),
valid_assets AS (
    SELECT
        cav.competitor_id,
        COUNT(*) AS valid_assets,
        COALESCE(SUM(COALESCE(rp.word_count, 0)), 0) AS valid_asset_words
    FROM v_content_asset_validity cav
    JOIN raw_pages rp ON rp.id = cav.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
    GROUP BY cav.competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(sp.pages_analyzed, 0) AS pages_analyzed,
    COALESCE(sp.total_words, 0) AS total_words,
    COALESCE(sp.total_words::FLOAT / NULLIF(twa.total_words, 0), 0) AS share_of_voice,
    COALESCE(sp.pages_analyzed, 0) AS crawled_ok_pages,
    COALESCE(va.valid_assets, 0) AS valid_assets,
    COALESCE(va.valid_asset_words, 0) AS valid_asset_words
FROM competitors c
CROSS JOIN total_words_all twa
LEFT JOIN successful_pages sp ON sp.competitor_id = c.id
LEFT JOIN valid_assets va ON va.competitor_id = c.id;

CREATE OR REPLACE VIEW v_competitor_sentiment AS
WITH sentiment_counts AS (
    SELECT
        competitor_id,
        COUNT(*) AS total_insights,
        COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
        COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
        COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
        COUNT(*) FILTER (WHERE sentiment = 'mixed') AS mixed_count,
        COUNT(*) FILTER (WHERE sentiment = 'not_found') AS not_found_count
    FROM page_insights
    GROUP BY competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(sc.total_insights, 0) AS total_insights,
    COALESCE(sc.positive_count, 0) AS positive_count,
    COALESCE(sc.negative_count, 0) AS negative_count,
    COALESCE(sc.neutral_count, 0) AS neutral_count,
    COALESCE(sc.mixed_count, 0) AS mixed_count,
    COALESCE(sc.not_found_count, 0) AS not_found_count,
    COALESCE(sc.positive_count::FLOAT / NULLIF(sc.total_insights, 0), 0) AS positive_share,
    COALESCE(sc.negative_count::FLOAT / NULLIF(sc.total_insights, 0), 0) AS negative_share,
    COALESCE(sc.neutral_count::FLOAT / NULLIF(sc.total_insights, 0), 0) AS neutral_share,
    COALESCE(sc.mixed_count::FLOAT / NULLIF(sc.total_insights, 0), 0) AS mixed_share,
    COALESCE(sc.not_found_count::FLOAT / NULLIF(sc.total_insights, 0), 0) AS not_found_share
FROM competitors c
LEFT JOIN sentiment_counts sc ON sc.competitor_id = c.id;

CREATE OR REPLACE VIEW v_competitor_pricing AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COUNT(pi.id) FILTER (
        WHERE pi.pricing_model IS NOT NULL
          AND btrim(pi.pricing_model) <> ''
          AND lower(btrim(pi.pricing_model)) <> 'not_found'
    ) AS pricing_mentions
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_competitor_features AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.key_features) = 'array'
                    THEN jsonb_array_length(pi.key_features)
                ELSE 0
            END
        ),
        0
    ) AS feature_mentions
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_competitor_claims AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.claims) = 'array'
                    THEN jsonb_array_length(pi.claims)
                ELSE 0
            END
        ),
        0
    ) AS claims_count
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_competitor_ctas AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.ctas) = 'array'
                    THEN jsonb_array_length(pi.ctas)
                ELSE 0
            END
        ),
        0
    ) AS cta_mentions
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_competitor_overview AS
SELECT
    sov.competitor_id,
    sov.competitor_name,
    sov.pages_analyzed,
    sov.total_words,
    sov.share_of_voice,
    sentiment.positive_share AS sentiment_positive_share,
    sentiment.negative_share AS sentiment_negative_share,
    sentiment.neutral_share AS sentiment_neutral_share,
    sentiment.mixed_share AS sentiment_mixed_share,
    sentiment.not_found_share AS sentiment_not_found_share,
    pricing.pricing_mentions,
    features.feature_mentions,
    claims.claims_count,
    ctas.cta_mentions,
    sov.crawled_ok_pages,
    sov.valid_assets,
    sov.valid_asset_words
FROM v_competitor_share_of_voice sov
JOIN v_competitor_sentiment sentiment
    ON sentiment.competitor_id = sov.competitor_id
JOIN v_competitor_pricing pricing
    ON pricing.competitor_id = sov.competitor_id
JOIN v_competitor_features features
    ON features.competitor_id = sov.competitor_id
JOIN v_competitor_claims claims
    ON claims.competitor_id = sov.competitor_id
JOIN v_competitor_ctas ctas
    ON ctas.competitor_id = sov.competitor_id;

CREATE OR REPLACE VIEW v_page_insights_dashboard AS
SELECT
    pi.id AS page_insight_id,
    pi.raw_page_id,
    pi.competitor_id,
    c.name AS competitor_name,
    c.category AS competitor_category,
    c.country AS competitor_country,
    COALESCE(pi.source_type, su.source_type) AS source_type,
    rp.url,
    rp.title,
    rp.word_count,
    rp.fetched_at,
    pi.extracted_at,
    pi.main_value_proposition,
    pi.target_audience,
    pi.tone_of_voice,
    pi.sentiment,
    pi.positioning,
    pi.pricing_model,
    pi.key_features,
    pi.claims,
    pi.objections_handled,
    pi.ctas,
    pi.differentiators,
    pi.summary
FROM page_insights pi
JOIN competitors c ON c.id = pi.competitor_id
LEFT JOIN raw_pages rp ON rp.id = pi.raw_page_id
LEFT JOIN source_urls su ON su.id = rp.source_url_id;

CREATE OR REPLACE VIEW v_topic_trends AS
SELECT
    td.id AS topic_document_id,
    td.raw_page_id,
    td.competitor_id,
    c.name AS competitor_name,
    c.category AS competitor_category,
    c.country AS competitor_country,
    su.source_type,
    rp.url,
    rp.title,
    rp.word_count,
    rp.fetched_at,
    td.topic_id,
    td.topic_label,
    td.topic_probability,
    td.created_at AS topic_created_at
FROM topic_documents td
JOIN competitors c ON c.id = td.competitor_id
LEFT JOIN raw_pages rp ON rp.id = td.raw_page_id
LEFT JOIN source_urls su ON su.id = rp.source_url_id;

CREATE OR REPLACE VIEW v_competitive_gaps AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COUNT(pi.id) AS total_insights,
    COUNT(pi.id) FILTER (
        WHERE pi.pricing_model IS NULL
           OR btrim(pi.pricing_model) = ''
           OR lower(btrim(pi.pricing_model)) = 'not_found'
    ) AS missing_pricing_count,
    COUNT(pi.id) FILTER (
        WHERE pi.positioning IS NULL
           OR btrim(pi.positioning) = ''
           OR lower(btrim(pi.positioning)) = 'not_found'
    ) AS missing_positioning_count,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.claims) = 'array'
                    THEN jsonb_array_length(pi.claims)
                ELSE 0
            END
        ),
        0
    ) AS claims_count,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.objections_handled) = 'array'
                    THEN jsonb_array_length(pi.objections_handled)
                ELSE 0
            END
        ),
        0
    ) AS objections_handled_count,
    COALESCE(
        SUM(
            CASE
                WHEN jsonb_typeof(pi.differentiators) = 'array'
                    THEN jsonb_array_length(pi.differentiators)
                ELSE 0
            END
        ),
        0
    ) AS differentiators_count
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_data_quality_issues AS
SELECT
    raw_page_id,
    competitor_id,
    competitor_name,
    url,
    source_type,
    title,
    word_count,
    has_insight,
    asset_validity_status,
    is_valid_content_asset,
    validity_reason,
    CASE
        WHEN validity_reason = 'crawl_failed' THEN 'refresh_crawl'
        WHEN validity_reason = 'empty_markdown' THEN 'review_crawl_output'
        WHEN validity_reason = 'low_word_count' THEN 'review_page_or_crawl'
        WHEN validity_reason = 'missing_insight' THEN 'rerun_extraction_or_review_page'
        WHEN validity_reason = 'template_or_placeholder' THEN 'review_url_or_rendering'
        ELSE 'review'
    END AS recommended_action
FROM v_content_asset_validity
WHERE is_valid_content_asset = FALSE;

CREATE OR REPLACE VIEW v_content_inventory AS
SELECT
    rp.id AS raw_page_id,
    rp.competitor_id,
    c.name AS competitor_name,
    c.is_owned_domain,
    rp.url,
    COALESCE(rp.asset_type, cav.source_type, su.source_type, 'other') AS asset_type,
    COALESCE(rp.title, '') AS title,
    COALESCE(rp.meta_description, '') AS meta_description,
    COALESCE(rp.h1, '') AS h1,
    COALESCE(rp.h2_list, '[]'::jsonb) AS h2_list,
    COALESCE(rp.h3_list, '[]'::jsonb) AS h3_list,
    rp.published_date,
    rp.modified_date,
    COALESCE(rp.word_count, 0) AS word_count,
    COALESCE(rp.internal_links_count, 0) AS internal_links_count,
    COALESCE(rp.external_links_count, 0) AS external_links_count,
    COALESCE(rp.faq_count, 0) AS faq_count,
    COALESCE(rp.table_count, 0) AS table_count,
    COALESCE(rp.conversion_links, '[]'::jsonb) AS conversion_links,
    CASE
        WHEN COALESCE(rp.content_depth_score, 0) > 0 THEN rp.content_depth_score
        ELSE LEAST(100, COALESCE(rp.word_count, 0) / 30)
    END AS content_depth_score,
    CASE
        WHEN COALESCE(rp.metadata_completeness_score, 0) > 0 THEN rp.metadata_completeness_score
        ELSE
            (CASE WHEN rp.title IS NOT NULL AND btrim(rp.title) <> '' THEN 30 ELSE 0 END)
            + (CASE WHEN rp.meta_description IS NOT NULL AND btrim(rp.meta_description) <> '' THEN 25 ELSE 0 END)
            + (CASE WHEN rp.h1 IS NOT NULL AND btrim(rp.h1) <> '' THEN 25 ELSE 0 END)
            + (CASE WHEN COALESCE(rp.h2_list, '[]'::jsonb) <> '[]'::jsonb THEN 20 ELSE 0 END)
    END AS metadata_completeness_score,
    COALESCE(rp.freshness_bucket, 'unknown') AS freshness_bucket,
    rp.fetched_at,
    cav.source_type,
    cav.has_insight,
    cav.asset_validity_status,
    cav.is_valid_content_asset,
    cav.validity_reason
FROM raw_pages rp
JOIN competitors c ON c.id = rp.competitor_id
LEFT JOIN source_urls su ON su.id = rp.source_url_id
JOIN v_content_asset_validity cav ON cav.raw_page_id = rp.id
WHERE cav.is_valid_content_asset = TRUE;

CREATE OR REPLACE VIEW v_asset_type_mix AS
WITH totals AS (
    SELECT competitor_id, COUNT(*) AS total_assets
    FROM v_content_inventory
    GROUP BY competitor_id
)
SELECT
    ci.competitor_id,
    ci.competitor_name,
    ci.asset_type,
    COUNT(*) AS assets_of_type,
    totals.total_assets,
    COUNT(*)::FLOAT / NULLIF(totals.total_assets, 0) AS asset_type_share
FROM v_content_inventory ci
JOIN totals ON totals.competitor_id = ci.competitor_id
GROUP BY ci.competitor_id, ci.competitor_name, ci.asset_type, totals.total_assets;

CREATE OR REPLACE VIEW v_content_depth_by_competitor AS
SELECT
    competitor_id,
    competitor_name,
    COUNT(*) AS total_content_assets,
    ROUND(AVG(content_depth_score)::numeric, 1) AS avg_content_depth_score,
    ROUND(AVG(metadata_completeness_score)::numeric, 1) AS avg_metadata_completeness_score,
    COUNT(*) FILTER (WHERE freshness_bucket = 'fresh') AS fresh_assets,
    COUNT(*) FILTER (WHERE freshness_bucket = 'recent') AS recent_assets,
    COUNT(*) FILTER (WHERE freshness_bucket = 'old') AS old_assets,
    COUNT(*) FILTER (WHERE freshness_bucket = 'unknown') AS undated_assets
FROM v_content_inventory
GROUP BY competitor_id, competitor_name;

CREATE OR REPLACE VIEW v_topic_coverage AS
SELECT
    td.topic_id,
    td.topic_label,
    td.competitor_id,
    c.name AS competitor_name,
    COUNT(*) AS document_count,
    ROUND(AVG(COALESCE(td.topic_probability, 0))::numeric, 3) AS avg_probability,
    COALESCE(pi.funnel_stage, td.funnel_stage, 'unknown') AS funnel_stage,
    jsonb_agg(DISTINCT rp.url) FILTER (WHERE rp.url IS NOT NULL) AS source_urls
FROM topic_documents td
JOIN v_content_asset_validity cav ON cav.raw_page_id = td.raw_page_id
JOIN competitors c ON c.id = td.competitor_id
LEFT JOIN raw_pages rp ON rp.id = td.raw_page_id
LEFT JOIN page_insights pi ON pi.raw_page_id = td.raw_page_id
WHERE cav.is_valid_content_asset = TRUE
GROUP BY td.topic_id, td.topic_label, td.competitor_id, c.name, COALESCE(pi.funnel_stage, td.funnel_stage, 'unknown');

CREATE OR REPLACE VIEW v_topic_share AS
WITH valid_topic_documents AS (
    SELECT td.*
    FROM topic_documents td
    JOIN v_content_asset_validity cav ON cav.raw_page_id = td.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
),
topic_totals AS (
    SELECT topic_id, COUNT(*) AS total_assets_on_topic
    FROM valid_topic_documents
    GROUP BY topic_id
),
topic_competitors AS (
    SELECT
        topic_id,
        COUNT(DISTINCT competitor_id) AS competitors_covering_topic,
        COUNT(*) AS assets_on_topic
    FROM valid_topic_documents
    GROUP BY topic_id
)
SELECT
    td.topic_id,
    td.topic_label,
    td.competitor_id,
    c.name AS competitor_name,
    COUNT(*) AS competitor_assets_on_topic,
    tt.total_assets_on_topic,
    COUNT(*)::FLOAT / NULLIF(tt.total_assets_on_topic, 0) AS topic_share,
    CASE
        WHEN tc.assets_on_topic <= 2 THEN 'insufficient data'
        WHEN tc.competitors_covering_topic <= 1 THEN 'low'
        WHEN tc.competitors_covering_topic >= 4 OR tc.assets_on_topic >= 7 THEN 'high'
        ELSE 'medium'
    END AS topic_saturation,
    CASE
        WHEN lower(td.topic_label) IN (
            'bounce / factory / demo aurora',
            'queue / demo boreale / bounce',
            'track / macros / barry'
        )
        THEN 'low'
        WHEN td.topic_label LIKE '%% [low confidence]'
          OR td.topic_label LIKE 'Topic %% [low confidence]'
        THEN 'low'
        ELSE 'normal'
    END AS label_confidence
FROM valid_topic_documents td
JOIN competitors c ON c.id = td.competitor_id
JOIN topic_totals tt ON tt.topic_id = td.topic_id
JOIN topic_competitors tc ON tc.topic_id = td.topic_id
GROUP BY td.topic_id, td.topic_label, td.competitor_id, c.name, tt.total_assets_on_topic, tc.competitors_covering_topic, tc.assets_on_topic;

CREATE OR REPLACE VIEW v_topic_gap AS
WITH owned_topics AS (
    SELECT DISTINCT td.topic_id
    FROM topic_documents td
    JOIN v_content_asset_validity cav ON cav.raw_page_id = td.raw_page_id
    JOIN competitors c ON c.id = td.competitor_id
    WHERE c.is_owned_domain = TRUE
      AND cav.is_valid_content_asset = TRUE
),
owned_config AS (
    SELECT EXISTS (SELECT 1 FROM competitors WHERE is_owned_domain = TRUE) AS has_owned_domain
),
owned_status AS (
    SELECT
        c.id AS owned_competitor_id,
        c.name AS owned_competitor_name,
        COALESCE(scorecards.score_confidence, 'low') AS owned_sample_confidence,
        COALESCE(scorecards.valid_assets, 0) AS owned_valid_assets,
        CASE
            WHEN COALESCE(scorecards.score_confidence, 'low') = 'low' THEN 'directional_only'
            ELSE 'fully_comparable'
        END AS gap_analysis_status,
        CASE
            WHEN COALESCE(scorecards.score_confidence, 'low') = 'low'
                THEN CONCAT(
                    'owned domain has low sample confidence: ',
                    COALESCE(scorecards.valid_assets, 0),
                    ' valid assets'
                )
            ELSE CONCAT(
                'owned domain sample confidence is ',
                COALESCE(scorecards.score_confidence, 'low')
            )
        END AS gap_analysis_reason
    FROM competitors c
    LEFT JOIN v_competitor_scorecards scorecards ON scorecards.competitor_id = c.id
    WHERE c.is_owned_domain = TRUE
)
SELECT
    ts.topic_id,
    ts.topic_label,
    ts.topic_saturation,
    SUM(ts.competitor_assets_on_topic) AS competitor_assets_on_topic,
    TRUE AS is_gap_vs_own_site,
    'missing_on_owned_site' AS gap_reason,
    ts.label_confidence,
    os.owned_competitor_id,
    os.owned_competitor_name,
    os.owned_sample_confidence,
    os.owned_valid_assets,
    os.gap_analysis_status,
    os.gap_analysis_reason
FROM v_topic_share ts
CROSS JOIN owned_config oc
CROSS JOIN owned_status os
LEFT JOIN owned_topics ot ON ot.topic_id = ts.topic_id
WHERE oc.has_owned_domain = TRUE
  AND ot.topic_id IS NULL
  AND ts.label_confidence = 'normal'
  AND ts.topic_saturation <> 'low'
  AND ts.topic_saturation <> 'insufficient data'
  AND lower(ts.topic_label) NOT LIKE '%%[low confidence]%%'
GROUP BY
    ts.topic_id,
    ts.topic_label,
    ts.topic_saturation,
    ts.label_confidence,
    os.owned_competitor_id,
    os.owned_competitor_name,
    os.owned_sample_confidence,
    os.owned_valid_assets,
    os.gap_analysis_status,
    os.gap_analysis_reason;

CREATE OR REPLACE VIEW v_controlled_topic_coverage AS
WITH valid_controlled_documents AS (
    SELECT
        ctd.*,
        rp.url,
        COALESCE(pi.funnel_stage, ctd.funnel_stage, 'unknown') AS resolved_funnel_stage
    FROM controlled_topic_documents ctd
    JOIN v_content_asset_validity cav ON cav.raw_page_id = ctd.raw_page_id
    LEFT JOIN raw_pages rp ON rp.id = ctd.raw_page_id
    LEFT JOIN page_insights pi ON pi.raw_page_id = ctd.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
),
controlled_totals AS (
    SELECT
        controlled_topic_id,
        COUNT(*) AS assets_on_controlled_topic,
        COUNT(DISTINCT competitor_id) AS competitors_covering_controlled_topic
    FROM valid_controlled_documents
    GROUP BY controlled_topic_id
)
SELECT
    vcd.controlled_topic_id,
    vcd.controlled_topic_label,
    CASE
        WHEN vcd.controlled_topic_id = 'unknown_other' THEN 'low'
        WHEN BOOL_OR(vcd.controlled_topic_confidence = 'high') THEN 'high'
        ELSE 'medium'
    END AS controlled_topic_confidence,
    CASE
        WHEN vcd.controlled_topic_id = 'unknown_other'
            THEN 'insufficient evidence for controlled topic assignment'
        ELSE MIN(vcd.controlled_topic_assignment_reason)
    END AS controlled_topic_assignment_reason,
    vcd.competitor_id,
    c.name AS competitor_name,
    COUNT(*) AS document_count,
    ct.assets_on_controlled_topic AS total_assets_on_topic,
    COUNT(*)::FLOAT / NULLIF(ct.assets_on_controlled_topic, 0) AS controlled_topic_share,
    CASE
        WHEN ct.assets_on_controlled_topic < 3
            THEN 'insufficient data'
        WHEN ct.competitors_covering_controlled_topic <= 1
          OR vcd.controlled_topic_id = 'unknown_other'
            THEN 'low'
        WHEN ct.competitors_covering_controlled_topic >= 4
          OR ct.assets_on_controlled_topic >= 7
            THEN 'high'
        ELSE 'medium'
    END AS topic_saturation,
    CASE
        WHEN vcd.controlled_topic_id = 'unknown_other' THEN 'low'
        ELSE 'normal'
    END AS label_confidence,
    vcd.resolved_funnel_stage AS funnel_stage,
    COALESCE(
        jsonb_agg(DISTINCT vcd.url) FILTER (WHERE vcd.url IS NOT NULL),
        '[]'::jsonb
    ) AS source_urls
FROM valid_controlled_documents vcd
JOIN competitors c ON c.id = vcd.competitor_id
JOIN controlled_totals ct ON ct.controlled_topic_id = vcd.controlled_topic_id
GROUP BY
    vcd.controlled_topic_id,
    vcd.controlled_topic_label,
    vcd.competitor_id,
    c.name,
    ct.assets_on_controlled_topic,
    ct.competitors_covering_controlled_topic,
    vcd.resolved_funnel_stage;

CREATE OR REPLACE VIEW v_controlled_topic_gap AS
WITH owned_topics AS (
    SELECT DISTINCT ctd.controlled_topic_id
    FROM controlled_topic_documents ctd
    JOIN v_content_asset_validity cav ON cav.raw_page_id = ctd.raw_page_id
    JOIN competitors c ON c.id = ctd.competitor_id
    WHERE c.is_owned_domain = TRUE
      AND cav.is_valid_content_asset = TRUE
      AND ctd.controlled_topic_id <> 'unknown_other'
),
owned_config AS (
    SELECT EXISTS (SELECT 1 FROM competitors WHERE is_owned_domain = TRUE) AS has_owned_domain
),
owned_status AS (
    SELECT
        c.id AS owned_competitor_id,
        c.name AS owned_competitor_name,
        COALESCE(scorecards.score_confidence, 'low') AS owned_sample_confidence,
        COALESCE(scorecards.valid_assets, 0) AS owned_valid_assets,
        CASE
            WHEN COALESCE(scorecards.score_confidence, 'low') = 'low' THEN 'directional_only'
            ELSE 'fully_comparable'
        END AS gap_analysis_status,
        CASE
            WHEN COALESCE(scorecards.score_confidence, 'low') = 'low'
                THEN CONCAT(
                    'owned domain has low sample confidence: ',
                    COALESCE(scorecards.valid_assets, 0),
                    ' valid assets'
                )
            ELSE CONCAT(
                'owned domain sample confidence is ',
                COALESCE(scorecards.score_confidence, 'low')
            )
        END AS gap_analysis_reason
    FROM competitors c
    LEFT JOIN v_competitor_scorecards scorecards ON scorecards.competitor_id = c.id
    WHERE c.is_owned_domain = TRUE
)
SELECT
    ctc.controlled_topic_id,
    ctc.controlled_topic_label,
    ctc.controlled_topic_confidence,
    ctc.topic_saturation,
    SUM(ctc.document_count) AS competitor_assets_on_topic,
    0::integer AS owned_assets_on_topic,
    TRUE AS is_gap_vs_own_site,
    'missing_on_owned_site' AS gap_reason,
    ctc.label_confidence,
    os.owned_competitor_id,
    os.owned_competitor_name,
    os.owned_sample_confidence,
    os.owned_valid_assets,
    os.gap_analysis_status,
    os.gap_analysis_reason
FROM v_controlled_topic_coverage ctc
CROSS JOIN owned_config oc
CROSS JOIN owned_status os
LEFT JOIN owned_topics ot ON ot.controlled_topic_id = ctc.controlled_topic_id
WHERE oc.has_owned_domain = TRUE
  AND ot.controlled_topic_id IS NULL
  AND ctc.controlled_topic_id <> 'unknown_other'
  AND ctc.label_confidence = 'normal'
  AND ctc.topic_saturation <> 'low'
  AND ctc.topic_saturation <> 'insufficient data'
GROUP BY
    ctc.controlled_topic_id,
    ctc.controlled_topic_label,
    ctc.controlled_topic_confidence,
    ctc.topic_saturation,
    ctc.label_confidence,
    os.owned_competitor_id,
    os.owned_competitor_name,
    os.owned_sample_confidence,
    os.owned_valid_assets,
    os.gap_analysis_status,
    os.gap_analysis_reason;

CREATE OR REPLACE VIEW v_classified_pain_points AS
WITH expanded AS (
    SELECT
        pi.id AS page_insight_id,
        pi.raw_page_id,
        pi.competitor_id,
        c.name AS competitor_name,
        rp.url AS source_url,
        pain_item.pain_point,
        CASE
            WHEN jsonb_typeof(pain_item.pain_point) = 'object'
                THEN COALESCE(
                    pain_item.pain_point ->> 'pain_point_text',
                    pain_item.pain_point ->> 'text',
                    ''
                )
            ELSE pain_item.pain_point #>> '{}'
        END AS extracted_pain_point_text,
        CASE
            WHEN jsonb_typeof(pain_item.pain_point) = 'object'
                THEN lower(btrim(COALESCE(pain_item.pain_point ->> 'pain_point_category', '')))
            ELSE ''
        END AS extracted_pain_point_category,
        CASE
            WHEN jsonb_typeof(pain_item.pain_point) = 'object'
                THEN lower(btrim(COALESCE(pain_item.pain_point ->> 'pain_point_evidence_type', '')))
            ELSE ''
        END AS extracted_pain_point_evidence_type,
        CASE
            WHEN jsonb_typeof(pain_item.pain_point) = 'object'
                THEN COALESCE(pain_item.pain_point ->> 'source_text', '')
            ELSE ''
        END AS source_text
    FROM page_insights pi
    JOIN competitors c ON c.id = pi.competitor_id
    JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
    LEFT JOIN raw_pages rp ON rp.id = pi.raw_page_id
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(pi.pain_points, '[]'::jsonb)) AS pain_item(pain_point)
    WHERE cav.is_valid_content_asset = TRUE
),
normalized AS (
    SELECT
        page_insight_id,
        raw_page_id,
        competitor_id,
        competitor_name,
        source_url,
        NULLIF(btrim(extracted_pain_point_text), '') AS pain_point_text,
        extracted_pain_point_category,
        extracted_pain_point_evidence_type,
        NULLIF(btrim(source_text), '') AS source_text
    FROM expanded
)
SELECT
    page_insight_id,
    raw_page_id,
    competitor_id,
    competitor_name,
    source_url,
    pain_point_text,
    CASE
        WHEN extracted_pain_point_category IN (
            'manual work',
            'repetitive workflow',
            'time cost',
            'export/bounce overhead',
            'review friction',
            'sync/versioning',
            'licensing complexity',
            'collaboration bottleneck',
            'approval bottleneck'
        ) THEN extracted_pain_point_category
        WHEN lower(pain_point_text) ~ 'manual|hands-on|by hand|cleanup' THEN 'manual work'
        WHEN lower(pain_point_text) ~ 'repetitive|repeatable|repeated|batch|routine' THEN 'repetitive workflow'
        WHEN lower(pain_point_text) ~ 'time-consuming|time consuming|save time|hours|faster|slow' THEN 'time cost'
        WHEN lower(pain_point_text) ~ 'export|bounce|stem|deliverable' THEN 'export/bounce overhead'
        WHEN lower(pain_point_text) ~ 'review|feedback|notes|revision' THEN 'review friction'
        WHEN lower(pain_point_text) ~ 'sync|synchronization|version|reference track' THEN 'sync/versioning'
        WHEN lower(pain_point_text) ~ 'licen[cs]e|subscription|seat|activation' THEN 'licensing complexity'
        WHEN lower(pain_point_text) ~ 'collaboration|collaborate|team|handoff|share' THEN 'collaboration bottleneck'
        WHEN lower(pain_point_text) ~ 'approval|approve|sign-off|sign off|signoff|stakeholder' THEN 'approval bottleneck'
        ELSE 'uncategorized'
    END AS pain_point_category,
    CASE
        WHEN extracted_pain_point_evidence_type IN ('explicit', 'inferred_from_benefit', 'keyword_fallback')
            THEN extracted_pain_point_evidence_type
        WHEN extracted_pain_point_evidence_type = 'not_found' THEN 'explicit'
        ELSE 'explicit'
    END AS pain_point_evidence_type,
    COALESCE(source_text, 'not_found') AS source_text
FROM normalized
WHERE pain_point_text IS NOT NULL
  AND lower(pain_point_text) NOT IN ('not_found', 'none', 'unknown');

CREATE OR REPLACE VIEW v_messaging_matrix AS
WITH valid_insights AS (
    SELECT pi.*
    FROM page_insights pi
    JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
),
insight_page_counts AS (
    SELECT
        pi.competitor_id,
        COUNT(DISTINCT pi.id) AS insight_pages
    FROM valid_insights pi
    GROUP BY pi.competitor_id
),
messaging_pillars AS (
    SELECT
        pi.competitor_id,
        jsonb_agg(DISTINCT pillar) FILTER (WHERE pillar IS NOT NULL) AS messaging_pillars
    FROM valid_insights pi
    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(pi.messaging_pillars, '[]'::jsonb)) AS pillar
    GROUP BY pi.competitor_id
),
value_proposition_themes AS (
    SELECT
        pi.competitor_id,
        jsonb_agg(DISTINCT theme) FILTER (WHERE theme IS NOT NULL) AS value_proposition_themes
    FROM valid_insights pi
    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(pi.value_proposition_themes, '[]'::jsonb)) AS theme
    GROUP BY pi.competitor_id
),
pain_points AS (
    SELECT
        cpp.competitor_id,
        jsonb_agg(DISTINCT cpp.pain_point_text) FILTER (WHERE cpp.pain_point_text IS NOT NULL) AS pain_points,
        jsonb_agg(
            DISTINCT jsonb_build_object(
                'pain_point_text', cpp.pain_point_text,
                'pain_point_category', cpp.pain_point_category,
                'pain_point_evidence_type', cpp.pain_point_evidence_type,
                'source_text', cpp.source_text
            )
        ) FILTER (WHERE cpp.pain_point_text IS NOT NULL) AS pain_point_details
    FROM v_classified_pain_points cpp
    GROUP BY cpp.competitor_id
),
proof_elements AS (
    SELECT
        pi.competitor_id,
        jsonb_agg(DISTINCT proof_element) FILTER (WHERE proof_element IS NOT NULL) AS proof_elements
    FROM valid_insights pi
    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(pi.proof_elements, '[]'::jsonb)) AS proof_element
    GROUP BY pi.competitor_id
),
score_aggregates AS (
    SELECT
        pi.competitor_id,
        ROUND(AVG(COALESCE(pi.genericity_score, 0))::numeric, 1) AS avg_genericity_score,
        ROUND(AVG(100 - COALESCE(pi.genericity_score, 0))::numeric, 1) AS differentiation_score,
        ROUND(
            COALESCE(
                SUM(CASE WHEN jsonb_typeof(pi.benefits) = 'array' THEN jsonb_array_length(pi.benefits) ELSE 0 END)::numeric
                / NULLIF(SUM(CASE WHEN jsonb_typeof(pi.features) = 'array' THEN jsonb_array_length(pi.features) ELSE 0 END), 0),
                0
            ),
            2
        ) AS benefit_vs_feature_ratio,
        MIN(NULLIF(pi.tone_label, 'not_found')) AS example_tone_label
    FROM valid_insights pi
    GROUP BY pi.competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(ipc.insight_pages, 0) AS insight_pages,
    COALESCE(mp.messaging_pillars, '[]'::jsonb) AS messaging_pillars,
    COALESCE(vpt.value_proposition_themes, '[]'::jsonb) AS value_proposition_themes,
    COALESCE(pp.pain_points, '[]'::jsonb) AS pain_points,
    COALESCE(pe.proof_elements, '[]'::jsonb) AS proof_elements,
    COALESCE(sa.avg_genericity_score, 0) AS avg_genericity_score,
    COALESCE(sa.differentiation_score, 0) AS differentiation_score,
    COALESCE(sa.benefit_vs_feature_ratio, 0) AS benefit_vs_feature_ratio,
    sa.example_tone_label,
    COALESCE(pp.pain_point_details, '[]'::jsonb) AS pain_point_details
FROM competitors c
LEFT JOIN insight_page_counts ipc ON ipc.competitor_id = c.id
LEFT JOIN messaging_pillars mp ON mp.competitor_id = c.id
LEFT JOIN value_proposition_themes vpt ON vpt.competitor_id = c.id
LEFT JOIN pain_points pp ON pp.competitor_id = c.id
LEFT JOIN proof_elements pe ON pe.competitor_id = c.id
LEFT JOIN score_aggregates sa ON sa.competitor_id = c.id;

CREATE OR REPLACE VIEW v_pain_point_coverage AS
WITH weighted_points AS (
    SELECT
        *,
        pain_point_text AS pain_point,
        CASE
            WHEN pain_point_category IS NOT NULL
                 AND pain_point_category <> ''
                 AND pain_point_category <> 'uncategorized'
                THEN pain_point_category
            ELSE pain_point_text
        END AS pain_point_group,
        CASE
            WHEN pain_point_evidence_type = 'explicit' THEN 3
            WHEN pain_point_evidence_type = 'inferred_from_benefit' THEN 2
            WHEN pain_point_evidence_type = 'keyword_fallback' THEN 0.5
            ELSE 0
        END AS evidence_weight
    FROM v_classified_pain_points
),
aggregated AS (
    SELECT
        pain_point_group AS pain_point,
        COUNT(DISTINCT competitor_id) AS competitors_mentioning_it,
        COUNT(*) AS frequency,
        jsonb_agg(DISTINCT source_url) FILTER (WHERE source_url IS NOT NULL) AS source_urls,
        jsonb_agg(DISTINCT pain_point_category) FILTER (WHERE pain_point_category IS NOT NULL) AS pain_point_categories,
        jsonb_agg(DISTINCT pain_point_evidence_type) FILTER (WHERE pain_point_evidence_type IS NOT NULL) AS pain_point_evidence_types,
        COUNT(*) FILTER (WHERE pain_point_evidence_type = 'explicit') AS explicit_frequency,
        COUNT(*) FILTER (WHERE pain_point_evidence_type = 'inferred_from_benefit') AS inferred_from_benefit_frequency,
        COUNT(*) FILTER (WHERE pain_point_evidence_type = 'keyword_fallback') AS keyword_fallback_frequency,
        COUNT(DISTINCT source_url) FILTER (WHERE pain_point_evidence_type = 'inferred_from_benefit') AS inferred_source_count,
        SUM(evidence_weight) AS weighted_evidence_score
    FROM weighted_points
    GROUP BY pain_point_group
)
SELECT
    pain_point,
    competitors_mentioning_it,
    frequency,
    source_urls,
    pain_point_categories,
    pain_point_evidence_types,
    explicit_frequency,
    inferred_from_benefit_frequency,
    keyword_fallback_frequency,
    inferred_source_count,
    weighted_evidence_score,
    CONCAT(
        'explicit=', explicit_frequency,
        '; inferred_from_benefit=', inferred_from_benefit_frequency,
        '; keyword_fallback=', keyword_fallback_frequency
    ) AS evidence_mix,
    CASE
        WHEN keyword_fallback_frequency = frequency THEN 'keyword_fallback'
        WHEN explicit_frequency >= inferred_from_benefit_frequency
             AND explicit_frequency >= keyword_fallback_frequency THEN 'explicit'
        WHEN inferred_from_benefit_frequency >= explicit_frequency
             AND inferred_from_benefit_frequency >= keyword_fallback_frequency THEN 'inferred_from_benefit'
        ELSE 'keyword_fallback'
    END AS dominant_evidence_type,
    ROUND(keyword_fallback_frequency::numeric / NULLIF(frequency, 0), 2) AS fallback_share,
    CASE
        WHEN keyword_fallback_frequency = frequency THEN 'fallback_only'
        WHEN keyword_fallback_frequency::float / NULLIF(frequency, 0) >= 0.5 THEN 'fallback_heavy'
        WHEN explicit_frequency >= inferred_from_benefit_frequency
             AND explicit_frequency >= keyword_fallback_frequency THEN 'explicit_heavy'
        ELSE 'mixed'
    END AS evidence_strength
FROM aggregated;

CREATE OR REPLACE VIEW v_pain_point_evidence_mix_by_competitor AS
SELECT
    competitor_name,
    pain_point_category,
    pain_point_evidence_type,
    COUNT(*) AS pain_point_count,
    jsonb_agg(DISTINCT pain_point_text) FILTER (WHERE pain_point_text IS NOT NULL) AS pain_points,
    jsonb_agg(DISTINCT source_url) FILTER (WHERE source_url IS NOT NULL) AS source_urls
FROM v_classified_pain_points
GROUP BY competitor_name, pain_point_category, pain_point_evidence_type;

CREATE OR REPLACE VIEW v_valid_page_insight_base AS
SELECT
    pi.id AS page_insight_id,
    pi.raw_page_id,
    pi.competitor_id,
    c.name AS competitor_name,
    c.is_owned_domain,
    rp.url,
    rp.title,
    COALESCE(rp.asset_type, pi.source_type, 'other') AS asset_type,
    COALESCE(rp.freshness_bucket, 'unknown') AS freshness_bucket,
    COALESCE(rp.content_depth_score, 0) AS content_depth_score,
    COALESCE(rp.metadata_completeness_score, 0) AS metadata_completeness_score,
    COALESCE(rp.word_count, 0) AS word_count,
    pi.source_type,
    pi.main_value_proposition,
    pi.target_audience,
    pi.positioning,
    pi.key_features,
    pi.proof_elements,
    pi.ctas,
    pi.cta_texts,
    pi.cta_types,
    pi.has_cta,
    COALESCE(pi.bofu_strength_score, 0) AS bofu_strength_score,
    COALESCE(pi.structure_score, 0) AS structure_score,
    COALESCE(pi.clarity_score, 0) AS clarity_score,
    COALESCE(pi.cta_alignment_score, 0) AS cta_alignment_score,
    COALESCE(pi.quality_warnings, '[]'::jsonb) AS quality_warnings,
    cav.asset_validity_status,
    cav.is_valid_content_asset,
    cav.validity_reason
FROM page_insights pi
JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
JOIN competitors c ON c.id = pi.competitor_id
LEFT JOIN raw_pages rp ON rp.id = pi.raw_page_id
WHERE cav.is_valid_content_asset = TRUE;

CREATE OR REPLACE VIEW v_classified_proof_elements AS
WITH expanded AS (
    SELECT
        vpi.page_insight_id,
        vpi.raw_page_id,
        vpi.competitor_id,
        vpi.competitor_name,
        proof_item.proof_element,
        CASE
            WHEN jsonb_typeof(proof_item.proof_element) = 'object'
                THEN COALESCE(
                    proof_item.proof_element ->> 'proof_text',
                    proof_item.proof_element ->> 'proof_source_text',
                    proof_item.proof_element ->> 'text',
                    proof_item.proof_element ->> 'claim',
                    ''
                )
            ELSE proof_item.proof_element #>> '{}'
        END AS proof_text,
        CASE
            WHEN jsonb_typeof(proof_item.proof_element) = 'object'
                THEN COALESCE(
                    proof_item.proof_element ->> 'proof_source_text',
                    proof_item.proof_element ->> 'source_text',
                    proof_item.proof_element ->> 'evidence',
                    ''
                )
            ELSE ''
        END AS proof_source_text,
        CASE
            WHEN jsonb_typeof(proof_item.proof_element) = 'object'
                THEN lower(btrim(COALESCE(proof_item.proof_element ->> 'proof_type', '')))
            ELSE ''
        END AS extracted_proof_type,
        CASE
            WHEN jsonb_typeof(proof_item.proof_element) = 'object'
                THEN lower(btrim(COALESCE(proof_item.proof_element ->> 'proof_strength', '')))
            ELSE ''
        END AS extracted_proof_strength
    FROM v_valid_page_insight_base vpi
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(vpi.proof_elements, '[]'::jsonb)) AS proof_item(proof_element)
),
normalized AS (
    SELECT
        expanded.*,
        lower(btrim(COALESCE(expanded.proof_text, ''))) AS proof_text_normalized,
        lower(btrim(CONCAT_WS(' ', expanded.proof_text, expanded.proof_source_text))) AS proof_evidence_text
    FROM expanded
),
typed AS (
    SELECT
        normalized.*,
        CASE
            WHEN normalized.extracted_proof_type IN (
                'testimonial',
                'customer_logo',
                'named_customer',
                'certification',
                'award',
                'case_study',
                'pricing',
                'trial_offer',
                'feature_evidence',
                'generic_claim',
                'unknown'
            ) THEN normalized.extracted_proof_type
            WHEN normalized.extracted_proof_type IN ('statistic', 'stats', 'statistics')
                AND normalized.proof_evidence_text ~* '([0-9]+(\.[0-9]+)?%%|[0-9]+x|[0-9]+\+|\m1000s\M|\mthousands\M|\mmillions\M|\m[0-9]+\s*(hours|minutes|days|weeks|seconds|records|projects|users|customers|teams|companies|tracks|sessions|files|dollars|percent|percentage|x|times)\M|\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M.*[0-9]|[0-9].*\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M)'
                THEN 'metric'
            WHEN normalized.extracted_proof_type IN ('metric')
                AND normalized.proof_evidence_text ~* '([0-9]+(\.[0-9]+)?%%|[0-9]+x|[0-9]+\+|\m1000s\M|\mthousands\M|\mmillions\M|\m[0-9]+\s*(hours|minutes|days|weeks|seconds|records|projects|users|customers|teams|companies|tracks|sessions|files|dollars|percent|percentage|x|times)\M|\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M.*[0-9]|[0-9].*\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M)'
                THEN 'metric'
            WHEN normalized.extracted_proof_type IN ('metric', 'statistic', 'stats', 'statistics')
                THEN 'generic_claim'
            WHEN normalized.extracted_proof_type IN ('customer testimonial', 'user testimonial', 'user testimonials', 'review', 'reviews', 'quote', 'customer quote')
                THEN 'testimonial'
            WHEN normalized.extracted_proof_type IN ('trial offer', 'trial-offer', 'free trial')
                THEN 'trial_offer'
            WHEN normalized.extracted_proof_type IN ('compatibility', 'version requirement', 'version release', 'product capability', 'product capabilities', 'update announcement')
                THEN 'feature_evidence'
            WHEN normalized.extracted_proof_type IN ('recognition')
                THEN 'award'
            WHEN normalized.extracted_proof_type IN ('customer logos', 'logo wall')
                THEN 'customer_logo'
            WHEN normalized.extracted_proof_type IN ('named customer', 'customer name')
                THEN 'named_customer'
            WHEN normalized.extracted_proof_type IN ('case study', 'customer story', 'success story', 'user story')
                AND normalized.proof_evidence_text ~* '\m(case study|case studies|customer story|customer stories|success story|real-world|helped us|integral part|producer|engineer|composer|artist|studio|university|ltd|inc|llc)\M'
                THEN 'case_study'
            WHEN normalized.extracted_proof_type IN ('feature description', 'feature recognition', 'demo content', 'statement', 'claim', 'promotion', 'community feedback', 'user story')
                AND normalized.proof_evidence_text ~* '([0-9]+(\.[0-9]+)?%%|[0-9]+x|[0-9]+\+|\m1000s\M|\mthousands\M|\mmillions\M|\m[0-9]+\s*(hours|minutes|days|weeks|seconds|records|projects|users|customers|teams|companies|tracks|sessions|files|dollars|percent|percentage|x|times)\M|\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M.*[0-9]|[0-9].*\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M)'
                THEN 'metric'
            WHEN normalized.extracted_proof_type IN ('feature description', 'feature recognition', 'demo content', 'statement', 'claim', 'promotion', 'community feedback', 'user story')
                AND normalized.proof_evidence_text ~* '\m(testimonial|testimonials|review|reviews|praised|praise|endorsed|quote|quoted|producer|engineer|composer|artist|studio|university|ltd|inc|llc|gearspace|staff pick)\M'
                THEN 'testimonial'
            WHEN normalized.extracted_proof_type IN ('feature description', 'feature recognition', 'demo content', 'statement', 'claim', 'promotion', 'community feedback', 'user story')
                THEN 'feature_evidence'
            WHEN normalized.proof_text_normalized = '' THEN 'unknown'
            WHEN normalized.proof_text_normalized ~* '\m(testimonial|testimonials|review|reviews|praised|praise|endorsed|quote|quoted)\M'
                THEN 'testimonial'
            WHEN normalized.proof_text_normalized ~* '\m(certified|certification|compliance|compliant|soc 2|iso 27001|day 0 compatibility)\M'
                THEN 'certification'
            WHEN normalized.proof_text_normalized ~* '\m(award|winner|won|emmy|recognized|featured in|featured by)\M'
                THEN 'award'
            WHEN normalized.proof_text_normalized ~* '\m(case study|case studies|customer story|customer stories|user story|user stories|success story|real-world production scenario)\M'
                THEN 'case_study'
            WHEN normalized.proof_text_normalized ~* '\m(pricing|price|priced|purchase|subscription|subscriptions|free trial|trial|discount|off|savings|one-time|per month|per year)\M'
                THEN 'pricing'
            WHEN normalized.proof_text_normalized ~* '\m(customer logo|customer logos|logo wall|trusted by|used by|customers include|clients include)\M'
                THEN 'customer_logo'
            WHEN normalized.proof_text_normalized ~* '([0-9]+(\.[0-9]+)?%%|[0-9]+x|[0-9]+\+|\m1000s\M|\mthousands\M|\mmillions\M|\m[0-9]+\s*(hours|minutes|days|weeks|seconds|records|projects|users|customers|teams|companies|tracks|sessions|files|dollars|percent|percentage|x|times)\M|\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M.*[0-9]|[0-9].*\m(save|saved|saves|saving|reduce|reduced|reduces|reduction|increase|increased|increases|faster|slower|benchmark|benchmarked|measured|roi|accuracy|uptime|latency|throughput|conversion|revenue|cost)\M)'
                THEN 'metric'
            WHEN normalized.proof_text_normalized ~* '\m(named customer|notable artists|notable customers|client|clients|customer|customers)\M'
                AND normalized.proof_text_normalized !~* '\m(customer service|relationship with customers)\M'
                THEN 'named_customer'
            ELSE 'generic_claim'
        END AS normalized_proof_type
    FROM normalized
),
strength_normalized AS (
    SELECT
        typed.*,
        CASE
            WHEN typed.normalized_proof_type IN ('metric', 'testimonial', 'case_study', 'certification', 'award')
                AND typed.extracted_proof_strength = 'low'
                THEN 'medium'
            WHEN typed.normalized_proof_type IN ('metric', 'testimonial', 'case_study', 'certification', 'award')
                THEN 'high'
            WHEN typed.normalized_proof_type IN ('customer_logo', 'named_customer')
                THEN 'medium'
            WHEN typed.normalized_proof_type IN ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')
                THEN 'low'
            ELSE 'unknown'
        END AS normalized_proof_strength,
        CASE
            WHEN typed.normalized_proof_type <> COALESCE(NULLIF(typed.extracted_proof_type, ''), 'unknown')
                THEN 'mapped extracted proof type to controlled taxonomy'
            WHEN typed.extracted_proof_strength = 'high'
                AND typed.normalized_proof_type IN ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')
                THEN 'downgraded commercial or generic proof from extracted high strength'
            WHEN typed.normalized_proof_type IN ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')
                THEN 'commercial or generic proof is low by default'
            WHEN typed.normalized_proof_type IN ('customer_logo', 'named_customer')
                THEN 'customer identity proof is medium by default'
            WHEN typed.normalized_proof_type IN ('metric', 'testimonial', 'case_study', 'certification', 'award')
                THEN 'eligible evidence type can support high strength'
            ELSE 'unknown or empty proof'
        END AS proof_normalization_reason
    FROM typed
)
SELECT
    strength_normalized.page_insight_id,
    strength_normalized.raw_page_id,
    strength_normalized.competitor_id,
    strength_normalized.competitor_name,
    NULLIF(btrim(COALESCE(strength_normalized.proof_text, '')), '') AS proof_text,
    strength_normalized.normalized_proof_type AS proof_type,
    strength_normalized.normalized_proof_strength AS proof_strength,
    CASE
        WHEN strength_normalized.normalized_proof_strength = 'high'
            THEN 25
        WHEN strength_normalized.normalized_proof_strength = 'medium'
            THEN 12
        WHEN strength_normalized.normalized_proof_strength = 'low'
            THEN 2
        ELSE 0
    END AS proof_weight,
    COALESCE(NULLIF(strength_normalized.extracted_proof_type, ''), 'unknown') AS extracted_proof_type,
    strength_normalized.normalized_proof_type,
    COALESCE(NULLIF(strength_normalized.extracted_proof_strength, ''), 'unknown') AS extracted_proof_strength,
    strength_normalized.normalized_proof_strength,
    strength_normalized.proof_normalization_reason,
    CONCAT_WS(
        ':',
        strength_normalized.normalized_proof_type,
        NULLIF(
            regexp_replace(
                lower(btrim(CONCAT_WS(' ', strength_normalized.proof_text, strength_normalized.proof_source_text))),
                '[^a-z0-9]+',
                ' ',
                'g'
            ),
            ''
        )
    ) AS proof_claim_key
FROM strength_normalized;

CREATE OR REPLACE VIEW v_proof_type_mix_by_competitor AS
WITH totals AS (
    SELECT
        competitor_id,
        COUNT(*) AS total_proof_elements
    FROM v_classified_proof_elements
    GROUP BY competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(cpe.proof_type, 'unknown') AS proof_type,
    COALESCE(cpe.proof_strength, 'unknown') AS proof_strength,
    COUNT(cpe.proof_text) AS proof_elements_count,
    COALESCE(
        COUNT(cpe.proof_text)::FLOAT / NULLIF(totals.total_proof_elements, 0),
        0
    ) AS proof_type_share,
    COALESCE(cpe.extracted_proof_type, 'unknown') AS extracted_proof_type,
    COALESCE(cpe.normalized_proof_type, 'unknown') AS normalized_proof_type,
    COALESCE(cpe.extracted_proof_strength, 'unknown') AS extracted_proof_strength,
    COALESCE(cpe.normalized_proof_strength, 'unknown') AS normalized_proof_strength,
    COALESCE(cpe.proof_normalization_reason, 'unknown or empty proof') AS proof_normalization_reason
FROM competitors c
LEFT JOIN v_classified_proof_elements cpe ON cpe.competitor_id = c.id
LEFT JOIN totals ON totals.competitor_id = c.id
GROUP BY
    c.id,
    c.name,
    COALESCE(cpe.proof_type, 'unknown'),
    COALESCE(cpe.proof_strength, 'unknown'),
    totals.total_proof_elements,
    COALESCE(cpe.extracted_proof_type, 'unknown'),
    COALESCE(cpe.normalized_proof_type, 'unknown'),
    COALESCE(cpe.extracted_proof_strength, 'unknown'),
    COALESCE(cpe.normalized_proof_strength, 'unknown'),
    COALESCE(cpe.proof_normalization_reason, 'unknown or empty proof');

CREATE OR REPLACE VIEW v_proof_density AS
WITH valid_proof_elements AS (
    SELECT cpe.*
    FROM v_classified_proof_elements cpe
    JOIN v_content_asset_validity cav ON cav.raw_page_id = cpe.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
),
deduplicated_proof_claims AS (
    SELECT DISTINCT ON (competitor_id, raw_page_id, proof_claim_key)
        *
    FROM valid_proof_elements
    WHERE proof_claim_key IS NOT NULL
    ORDER BY competitor_id, raw_page_id, proof_claim_key, proof_weight DESC, proof_text
),
proof_counts AS (
    SELECT
        competitor_id,
        COUNT(*) AS proof_elements_count,
        COUNT(*) FILTER (WHERE proof_strength = 'high') AS strong_proof_elements_count,
        SUM(proof_weight) AS weighted_proof_points
    FROM deduplicated_proof_claims
    GROUP BY competitor_id
),
asset_counts AS (
    SELECT competitor_id, COUNT(*) AS total_assets
    FROM v_content_asset_validity
    WHERE is_valid_content_asset = TRUE
    GROUP BY competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(pc.proof_elements_count, 0) AS proof_elements_count,
    COALESCE(ac.total_assets, 0) AS total_assets,
    COALESCE(pc.proof_elements_count::FLOAT / NULLIF(ac.total_assets, 0), 0) AS proof_density,
    COALESCE(pc.strong_proof_elements_count, 0) AS strong_proof_elements_count,
    COALESCE(pc.weighted_proof_points, 0) AS weighted_proof_points,
    COALESCE(pc.strong_proof_elements_count::FLOAT / NULLIF(ac.total_assets, 0), 0) AS strong_proof_density,
    COALESCE(pc.weighted_proof_points::FLOAT / NULLIF(ac.total_assets, 0), 0) AS weighted_proof_points_per_asset
FROM competitors c
LEFT JOIN proof_counts pc ON pc.competitor_id = c.id
LEFT JOIN asset_counts ac ON ac.competitor_id = c.id;

CREATE OR REPLACE VIEW v_funnel_mix AS
WITH valid_insights AS (
    SELECT pi.*
    FROM page_insights pi
    JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
),
totals AS (
    SELECT competitor_id, COUNT(*) AS total_assets
    FROM valid_insights
    GROUP BY competitor_id
)
SELECT
    pi.competitor_id,
    c.name AS competitor_name,
    COALESCE(pi.funnel_stage, 'unknown') AS funnel_stage,
    COUNT(*) AS assets_in_stage,
    totals.total_assets,
    COUNT(*)::FLOAT / NULLIF(totals.total_assets, 0) AS funnel_stage_share
FROM valid_insights pi
JOIN competitors c ON c.id = pi.competitor_id
JOIN totals ON totals.competitor_id = pi.competitor_id
GROUP BY pi.competitor_id, c.name, COALESCE(pi.funnel_stage, 'unknown'), totals.total_assets;

CREATE OR REPLACE VIEW v_classified_ctas AS
WITH indexed_ctas AS (
    SELECT
        vpi.page_insight_id,
        vpi.competitor_id,
        vpi.competitor_name,
        vpi.url AS source_url,
        cta_index.position,
        vpi.ctas -> (cta_index.position - 1) AS cta_item,
        vpi.cta_texts ->> (cta_index.position - 1) AS cta_text_item,
        vpi.cta_types ->> (cta_index.position - 1) AS cta_type_item
    FROM v_valid_page_insight_base vpi
    CROSS JOIN LATERAL generate_series(
        1,
        GREATEST(
            CASE WHEN jsonb_typeof(vpi.ctas) = 'array' THEN jsonb_array_length(vpi.ctas) ELSE 0 END,
            CASE WHEN jsonb_typeof(vpi.cta_texts) = 'array' THEN jsonb_array_length(vpi.cta_texts) ELSE 0 END,
            CASE WHEN jsonb_typeof(vpi.cta_types) = 'array' THEN jsonb_array_length(vpi.cta_types) ELSE 0 END
        )
    ) AS cta_index(position)
),
normalized_ctas AS (
    SELECT
        page_insight_id,
        competitor_id,
        competitor_name,
        source_url,
        COALESCE(
            NULLIF(btrim(cta_text_item), ''),
            NULLIF(btrim(
                CASE
                    WHEN jsonb_typeof(cta_item) = 'object'
                        THEN COALESCE(cta_item ->> 'cta_text', cta_item ->> 'text', cta_item ->> 'label')
                    WHEN jsonb_typeof(cta_item) = 'string'
                        THEN cta_item #>> '{}'
                    ELSE NULL
                END
            ), '')
        ) AS cta_text,
        COALESCE(
            NULLIF(btrim(cta_type_item), ''),
            NULLIF(btrim(
                CASE
                    WHEN jsonb_typeof(cta_item) = 'object'
                        THEN COALESCE(cta_item ->> 'cta_type', cta_item ->> 'type')
                    ELSE NULL
                END
            ), '')
        ) AS cta_type,
        lower(NULLIF(btrim(
            CASE
                WHEN jsonb_typeof(cta_item) = 'object'
                    THEN COALESCE(cta_item ->> 'cta_class', cta_item ->> 'class')
                ELSE NULL
            END
        ), '')) AS explicit_cta_class
    FROM indexed_ctas
),
classification_inputs AS (
    SELECT
        page_insight_id,
        competitor_id,
        competitor_name,
        source_url,
        cta_text,
        cta_type,
        explicit_cta_class,
        lower(btrim(COALESCE(NULLIF(cta_type, ''), ''))) AS normalized_cta_type,
        lower(btrim(COALESCE(NULLIF(cta_text, ''), ''))) AS normalized_cta_text
    FROM normalized_ctas
)
SELECT
    page_insight_id,
    competitor_id,
    competitor_name,
    source_url,
    cta_text,
    cta_type,
    CASE
        WHEN explicit_cta_class IN ('primary', 'secondary', 'navigation', 'footer', 'unknown')
            THEN explicit_cta_class
        WHEN normalized_cta_type IN ('', 'other', 'not_found', 'none', 'unknown')
             AND normalized_cta_text IN ('', 'other', 'not_found', 'none', 'unknown')
            THEN 'unknown'
        WHEN CONCAT_WS(' ', normalized_cta_type, normalized_cta_text)
            ~ '(^|[^a-z])(privacy|terms|cookies|cookie policy|legal|sitemap|copyright|facebook|linkedin|twitter|x.com|instagram|youtube)([^a-z]|$)'
            THEN 'footer'
        WHEN CONCAT_WS(' ', normalized_cta_type, normalized_cta_text)
            ~ '(^|[^a-z])(home|features|blog|resources|about|careers|jobs|login|log in|sign in|support|help|menu|navigation)([^a-z]|$)'
            THEN 'navigation'
        WHEN CONCAT_WS(' ', normalized_cta_type, normalized_cta_text)
            ~ '(^|[^a-z])(book demo|start trial|contact sales|request quote|buy now|sign up|signup|get started|view pricing)([^a-z]|$)'
            THEN 'primary'
        WHEN CONCAT_WS(' ', normalized_cta_type, normalized_cta_text)
            ~ '(^|[^a-z])(learn more|download|watch|guide|docs|documentation|read more)([^a-z]|$)'
            THEN 'secondary'
        ELSE 'unknown'
    END AS cta_class
FROM classification_inputs;

CREATE OR REPLACE VIEW v_cta_coverage_by_competitor AS
WITH valid_insights AS (
    SELECT pi.*
    FROM page_insights pi
    JOIN v_content_asset_validity cav ON cav.raw_page_id = pi.raw_page_id
    WHERE cav.is_valid_content_asset = TRUE
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COUNT(DISTINCT pi.id) AS total_insight_pages,
    COUNT(DISTINCT pi.id) FILTER (
        WHERE classified.cta_class IN ('primary', 'secondary', 'navigation', 'footer', 'unknown')
    ) AS pages_with_cta,
    COALESCE(
        COUNT(DISTINCT pi.id) FILTER (
            WHERE classified.cta_class IN ('primary', 'secondary', 'navigation', 'footer', 'unknown')
        )::FLOAT / NULLIF(COUNT(DISTINCT pi.id), 0),
        0
    ) AS cta_coverage,
    CASE
        WHEN COUNT(DISTINCT pi.id) < 3 THEN 'low'
        WHEN COUNT(DISTINCT pi.id) < 10 THEN 'medium'
        ELSE 'high'
    END AS sample_confidence,
    COUNT(DISTINCT pi.id) FILTER (
        WHERE classified.cta_class IN ('primary', 'secondary', 'navigation', 'footer', 'unknown')
    ) AS pages_with_any_cta,
    COALESCE(
        COUNT(DISTINCT pi.id) FILTER (
            WHERE classified.cta_class IN ('primary', 'secondary', 'navigation', 'footer', 'unknown')
        )::FLOAT / NULLIF(COUNT(DISTINCT pi.id), 0),
        0
    ) AS any_cta_coverage,
    COUNT(DISTINCT pi.id) FILTER (
        WHERE classified.cta_class = 'primary'
    ) AS pages_with_conversion_cta,
    COALESCE(
        COUNT(DISTINCT pi.id) FILTER (
            WHERE classified.cta_class = 'primary'
        )::FLOAT / NULLIF(COUNT(DISTINCT pi.id), 0),
        0
    ) AS conversion_cta_coverage,
    COUNT(DISTINCT pi.id) FILTER (
        WHERE classified.cta_class = 'secondary'
    ) AS pages_with_secondary_cta,
    COALESCE(
        COUNT(DISTINCT pi.id) FILTER (
            WHERE classified.cta_class = 'secondary'
        )::FLOAT / NULLIF(COUNT(DISTINCT pi.id), 0),
        0
    ) AS secondary_cta_coverage,
    COUNT(DISTINCT pi.id) AS total_valid_insight_pages
FROM competitors c
LEFT JOIN valid_insights pi ON pi.competitor_id = c.id
LEFT JOIN v_classified_ctas classified ON classified.page_insight_id = pi.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_cta_type_mix_by_competitor AS
WITH type_counts AS (
    SELECT
        competitor_id,
        competitor_name,
        cta_class AS cta_type,
        COUNT(*) AS cta_type_count
    FROM v_classified_ctas
    GROUP BY competitor_id, competitor_name, cta_class
),
type_totals AS (
    SELECT
        competitor_id,
        SUM(cta_type_count) AS total_cta_type_count
    FROM type_counts
    GROUP BY competitor_id
)
SELECT
    tc.competitor_id,
    tc.competitor_name,
    tc.cta_type,
    tc.cta_type_count,
    COALESCE(tc.cta_type_count::FLOAT / NULLIF(tt.total_cta_type_count, 0), 0) AS cta_type_share
FROM type_counts tc
JOIN type_totals tt ON tt.competitor_id = tc.competitor_id;

CREATE OR REPLACE VIEW v_cta_intelligence AS
SELECT
    competitor_id,
    competitor_name,
    total_insight_pages AS total_pages,
    pages_with_any_cta AS pages_with_cta,
    any_cta_coverage AS cta_coverage,
    NULL::text AS cta_type,
    0::bigint AS cta_type_count
FROM v_cta_coverage_by_competitor;

CREATE OR REPLACE VIEW v_conversion_links AS
SELECT
    pi.competitor_id,
    c.name AS competitor_name,
    rp.url AS source_url,
    conversion_link
FROM page_insights pi
JOIN competitors c ON c.id = pi.competitor_id
LEFT JOIN raw_pages rp ON rp.id = pi.raw_page_id
CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(pi.conversion_links, rp.conversion_links, '[]'::jsonb)) AS conversion_link;

CREATE OR REPLACE VIEW v_bofu_strength AS
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    ROUND(AVG(COALESCE(pi.bofu_strength_score, 0))::numeric, 1) AS avg_bofu_strength_score,
    COUNT(pi.id) FILTER (WHERE pi.funnel_stage = 'BOFU') AS bofu_assets,
    COALESCE(
        COUNT(pi.id) FILTER (WHERE pi.has_case_study_signal = TRUE)::FLOAT
        / NULLIF(COUNT(pi.id), 0),
        0
    ) AS case_study_density
FROM competitors c
LEFT JOIN page_insights pi ON pi.competitor_id = c.id
GROUP BY c.id, c.name;

CREATE OR REPLACE VIEW v_content_quality AS
-- Unknown freshness policy:
-- blog/changelog/release_notes/updates/news freshness_bucket = 'unknown' THEN 10
-- homepage/pricing/product freshness_bucket = 'unknown' THEN 45
WITH proof_scores AS (
    WITH deduplicated_proof_claims AS (
        SELECT DISTINCT ON (raw_page_id, proof_claim_key)
            *
        FROM v_classified_proof_elements
        WHERE proof_claim_key IS NOT NULL
        ORDER BY raw_page_id, proof_claim_key, proof_weight DESC, proof_text
    )
    SELECT
        raw_page_id,
        COUNT(*) AS proof_elements_count,
        COUNT(*) FILTER (WHERE normalized_proof_strength = 'high') AS strong_proof_elements_count,
        COUNT(*) FILTER (WHERE normalized_proof_strength = 'medium') AS medium_proof_elements_count,
        COUNT(*) FILTER (WHERE normalized_proof_strength = 'low') AS low_proof_elements_count,
        COUNT(*) FILTER (WHERE normalized_proof_strength = 'unknown') AS unknown_proof_elements_count,
        COUNT(*) FILTER (
            WHERE normalized_proof_type IN ('pricing', 'trial_offer', 'feature_evidence', 'generic_claim')
        ) AS low_or_generic_proof_elements_count,
        COALESCE(SUM(proof_weight), 0) AS raw_weighted_proof_score
    FROM deduplicated_proof_claims
    GROUP BY raw_page_id
),
cta_scores AS (
    SELECT
        page_insight_id,
        COUNT(*) FILTER (WHERE cta_class = 'primary') AS primary_cta_count,
        COUNT(*) FILTER (WHERE cta_class = 'secondary') AS secondary_cta_count,
        COUNT(*) FILTER (WHERE cta_class IN ('navigation', 'footer', 'unknown')) AS non_conversion_cta_count
    FROM v_classified_ctas
    GROUP BY page_insight_id
),
base AS (
    SELECT
        vpi.raw_page_id,
        vpi.competitor_id,
        vpi.competitor_name,
        vpi.is_owned_domain,
        vpi.url,
        vpi.title,
        vpi.asset_type,
        vpi.freshness_bucket,
        vpi.bofu_strength_score,
        CASE
            WHEN COALESCE(vpi.content_depth_score, 0) > 0 THEN vpi.content_depth_score
            ELSE LEAST(100, COALESCE(vpi.word_count, 0) / 30)
        END AS depth_score,
        COALESCE(ps.proof_elements_count, 0) AS proof_elements_count,
        COALESCE(ps.strong_proof_elements_count, 0) AS strong_proof_elements_count,
        COALESCE(ps.medium_proof_elements_count, 0) AS medium_proof_elements_count,
        COALESCE(ps.low_proof_elements_count, 0) AS low_proof_elements_count,
        COALESCE(ps.low_or_generic_proof_elements_count, 0) AS low_or_generic_proof_elements_count,
        COALESCE(ps.raw_weighted_proof_score, 0) AS raw_weighted_proof_score,
        LEAST(100, COALESCE(ps.raw_weighted_proof_score, 0))::integer AS raw_proof_score,
        CASE
            WHEN COALESCE(ps.strong_proof_elements_count, 0) > 0 THEN 'high'
            WHEN COALESCE(ps.medium_proof_elements_count, 0) > 0 THEN 'medium'
            WHEN COALESCE(ps.low_proof_elements_count, 0) > 0 THEN 'low'
            ELSE 'none'
        END AS quality_evidence_strength,
        CASE
            WHEN COALESCE(ps.proof_elements_count, 0) = 0 THEN 0
            WHEN COALESCE(ps.strong_proof_elements_count, 0) = 0
                 AND COALESCE(ps.medium_proof_elements_count, 0) = 0
                THEN LEAST(10, COALESCE(ps.raw_weighted_proof_score, 0))
            WHEN COALESCE(ps.strong_proof_elements_count, 0) = 0
                 AND COALESCE(ps.low_or_generic_proof_elements_count, 0) * 2 >= COALESCE(ps.proof_elements_count, 0)
                THEN LEAST(25, COALESCE(ps.raw_weighted_proof_score, 0))
            ELSE LEAST(100, COALESCE(ps.raw_weighted_proof_score, 0))
        END::integer AS proof_score,
        CASE
            WHEN COALESCE(ps.proof_elements_count, 0) = 0 THEN NULL
            WHEN COALESCE(ps.strong_proof_elements_count, 0) = 0
                 AND COALESCE(ps.medium_proof_elements_count, 0) = 0
                THEN 'proof contribution capped: normalized evidence is only low or generic'
            WHEN COALESCE(ps.strong_proof_elements_count, 0) = 0
                 AND COALESCE(ps.low_or_generic_proof_elements_count, 0) * 2 >= COALESCE(ps.proof_elements_count, 0)
                THEN 'proof contribution capped: low/generic normalized evidence is the majority'
            ELSE NULL
        END AS proof_cap_reason,
        CASE
            WHEN lower(vpi.asset_type) IN ('blog', 'changelog', 'release_notes', 'release notes', 'updates', 'news')
                 AND vpi.freshness_bucket = 'unknown' THEN 10
            WHEN lower(vpi.asset_type) IN ('homepage', 'pricing', 'product')
                 AND vpi.freshness_bucket = 'unknown' THEN 45
            WHEN vpi.freshness_bucket = 'fresh' THEN 100
            WHEN vpi.freshness_bucket = 'recent' THEN 75
            WHEN vpi.freshness_bucket = 'old' THEN 35
            ELSE 20
        END AS freshness_score,
        CASE
            WHEN vpi.freshness_bucket = 'unknown' THEN 'unavailable'
            ELSE 'high'
        END AS freshness_confidence,
        CASE
            WHEN COALESCE(vpi.structure_score, 0) > 0 THEN vpi.structure_score
            WHEN COALESCE(vpi.metadata_completeness_score, 0) > 0 THEN vpi.metadata_completeness_score
            ELSE CASE WHEN vpi.title IS NOT NULL AND btrim(vpi.title) <> '' THEN 30 ELSE 0 END
        END AS structure_score,
        CASE
            WHEN COALESCE(vpi.clarity_score, 0) > 0 THEN vpi.clarity_score
            ELSE
                (CASE WHEN vpi.main_value_proposition IS NOT NULL AND lower(vpi.main_value_proposition) <> 'not_found' THEN 35 ELSE 0 END)
                + (CASE WHEN vpi.target_audience IS NOT NULL AND lower(vpi.target_audience) <> 'not_found' THEN 25 ELSE 0 END)
                + (CASE WHEN vpi.positioning IS NOT NULL AND lower(vpi.positioning) <> 'not_found' THEN 20 ELSE 0 END)
                + (CASE WHEN jsonb_typeof(vpi.key_features) = 'array' AND jsonb_array_length(vpi.key_features) > 0 THEN 20 ELSE 0 END)
        END AS clarity_score,
        CASE
            WHEN COALESCE(cs.primary_cta_count, 0) > 0
                THEN CASE
                    WHEN COALESCE(vpi.cta_alignment_score, 0) > 0 THEN vpi.cta_alignment_score
                    ELSE 80
                END
            WHEN COALESCE(cs.secondary_cta_count, 0) > 0
                THEN LEAST(
                    45,
                    CASE
                        WHEN COALESCE(vpi.cta_alignment_score, 0) > 0 THEN vpi.cta_alignment_score
                        ELSE 45
                    END
                )
            WHEN COALESCE(cs.non_conversion_cta_count, 0) > 0
                THEN LEAST(
                    25,
                    CASE
                        WHEN COALESCE(vpi.cta_alignment_score, 0) > 0 THEN vpi.cta_alignment_score
                        ELSE 25
                    END
                )
            WHEN vpi.has_cta = TRUE OR (jsonb_typeof(vpi.ctas) = 'array' AND jsonb_array_length(vpi.ctas) > 0) THEN 35
            ELSE 20
        END AS cta_alignment_score,
        CASE
            WHEN COALESCE(cs.primary_cta_count, 0) > 0 THEN 'conversion'
            WHEN COALESCE(cs.secondary_cta_count, 0) > 0 THEN 'secondary_only'
            WHEN COALESCE(cs.non_conversion_cta_count, 0) > 0 THEN 'non_conversion_only'
            WHEN vpi.has_cta = TRUE OR (jsonb_typeof(vpi.ctas) = 'array' AND jsonb_array_length(vpi.ctas) > 0) THEN 'unclassified'
            ELSE 'none'
        END AS cta_signal_strength,
        CASE
            WHEN COALESCE(cs.secondary_cta_count, 0) > 0
                 AND COALESCE(cs.primary_cta_count, 0) = 0
                THEN 'CTA contribution capped: only secondary CTAs were found'
            WHEN COALESCE(cs.non_conversion_cta_count, 0) > 0
                 AND COALESCE(cs.primary_cta_count, 0) = 0
                 AND COALESCE(cs.secondary_cta_count, 0) = 0
                THEN 'CTA contribution capped: only navigation, footer, or unknown CTAs were found'
            ELSE NULL
        END AS cta_cap_reason,
        vpi.quality_warnings AS base_quality_warnings,
        vpi.asset_validity_status,
        vpi.is_valid_content_asset,
        vpi.validity_reason
    FROM v_valid_page_insight_base vpi
    LEFT JOIN proof_scores ps ON ps.raw_page_id = vpi.raw_page_id
    LEFT JOIN cta_scores cs ON cs.page_insight_id = vpi.page_insight_id
),
scored AS (
    SELECT
        base.*,
        ROUND(
            (0.25 / 0.85) * base.depth_score
            + (0.20 / 0.85) * base.proof_score
            + (0.15 / 0.85) * base.structure_score
            + (0.15 / 0.85) * base.clarity_score
            + (0.10 / 0.85) * base.cta_alignment_score
        )::integer AS raw_content_quality_score
    FROM base
),
explained AS (
    SELECT
        scored.*,
        CASE
            WHEN scored.depth_score < 35
                 AND scored.quality_evidence_strength <> 'high'
                THEN LEAST(scored.raw_content_quality_score, 49)
            ELSE scored.raw_content_quality_score
        END AS content_quality_score,
        scored.base_quality_warnings
            || CASE
                WHEN scored.freshness_bucket = 'unknown'
                     AND NOT (scored.base_quality_warnings ? 'undated_content')
                    THEN '["undated_content"]'::jsonb
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN scored.depth_score < 35
                     AND NOT (scored.base_quality_warnings ? 'low_depth')
                    THEN '["low_depth"]'::jsonb
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN scored.proof_cap_reason IS NOT NULL
                     AND NOT (scored.base_quality_warnings ? 'proof_capped')
                    THEN '["proof_capped"]'::jsonb
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN scored.cta_cap_reason IS NOT NULL
                     AND NOT (scored.base_quality_warnings ? 'cta_capped')
                    THEN '["cta_capped"]'::jsonb
                ELSE '[]'::jsonb
            END AS quality_warnings
    FROM scored
)
SELECT
    explained.raw_page_id,
    explained.competitor_id,
    explained.competitor_name,
    explained.url,
    explained.title,
    explained.asset_type,
    explained.depth_score,
    explained.bofu_strength_score,
    explained.proof_elements_count,
    explained.strong_proof_elements_count,
    explained.raw_weighted_proof_score AS weighted_proof_points,
    explained.proof_score,
    explained.freshness_score,
    explained.structure_score,
    explained.clarity_score,
    explained.cta_alignment_score,
    explained.content_quality_score,
    explained.quality_warnings,
    explained.asset_validity_status,
    explained.is_valid_content_asset,
    explained.validity_reason,
    explained.freshness_confidence,
    CASE
        WHEN explained.depth_score < 35 THEN 'low'
        WHEN explained.proof_cap_reason IS NOT NULL THEN 'low'
        WHEN explained.cta_cap_reason IS NOT NULL THEN 'low'
        WHEN explained.content_quality_score >= 85 THEN 'high'
        ELSE 'medium'
    END AS score_confidence,
    CASE
        WHEN explained.content_quality_score IS NULL THEN 'unavailable'
        WHEN explained.content_quality_score < 50 THEN 'weak'
        WHEN explained.content_quality_score < 75 THEN 'adequate'
        WHEN explained.content_quality_score < 85 THEN 'strong'
        WHEN explained.depth_score >= 35
          AND explained.quality_evidence_strength = 'high'
          AND explained.proof_cap_reason IS NULL
          AND explained.cta_cap_reason IS NULL THEN 'high_confidence_strong'
        ELSE 'strong'
    END AS quality_bucket,
    CONCAT_WS(
        '; ',
        explained.proof_cap_reason,
        explained.cta_cap_reason,
        CASE
            WHEN explained.depth_score < 35
                 AND explained.quality_evidence_strength <> 'high'
                THEN 'low depth limits asset score without high normalized evidence'
            ELSE NULL
        END,
        CASE
            WHEN explained.proof_cap_reason IS NULL
                 AND explained.cta_cap_reason IS NULL
                 AND NOT (explained.depth_score < 35 AND explained.quality_evidence_strength <> 'high')
                 AND explained.content_quality_score >= 85
                THEN 'strong normalized evidence and complete structure'
            WHEN explained.proof_cap_reason IS NULL
                 AND explained.cta_cap_reason IS NULL
                 AND NOT (explained.depth_score < 35 AND explained.quality_evidence_strength <> 'high')
                THEN 'balanced quality signals'
            ELSE NULL
        END
    ) AS quality_reason,
    explained.content_quality_score AS quality_score,
    CASE
        WHEN explained.depth_score < 35 THEN 'low'
        WHEN explained.proof_cap_reason IS NOT NULL THEN 'low'
        WHEN explained.cta_cap_reason IS NOT NULL THEN 'low'
        WHEN explained.content_quality_score >= 85 THEN 'high'
        ELSE 'medium'
    END AS quality_confidence,
    explained.quality_evidence_strength AS quality_evidence_strength,
    explained.is_owned_domain
FROM explained;

CREATE OR REPLACE VIEW v_competitor_scorecards AS
WITH scorecard_assets AS (
    SELECT
        competitor_id,
        COUNT(*) FILTER (WHERE is_valid_content_asset = TRUE) AS valid_assets,
        COUNT(*) FILTER (
            WHERE is_valid_content_asset = TRUE
               OR validity_reason = 'missing_insight'
        ) AS extraction_eligible_assets,
        COUNT(*) FILTER (
            WHERE is_valid_content_asset = TRUE
              AND has_insight = TRUE
        ) AS insight_pages
    FROM v_content_asset_validity
    WHERE is_valid_content_asset = TRUE
       OR validity_reason = 'missing_insight'
    GROUP BY competitor_id
),
quality_scores AS (
    SELECT
        competitor_id,
        ROUND(AVG(content_quality_score)::numeric, 1) AS avg_content_quality_score,
        ROUND(AVG(depth_score)::numeric, 1) AS avg_content_depth_score,
        ROUND(AVG(structure_score)::numeric, 1) AS avg_metadata_completeness_score,
        COUNT(*) FILTER (WHERE score_confidence = 'high') AS high_asset_score_confidence_assets,
        COUNT(*) FILTER (WHERE score_confidence = 'medium') AS medium_asset_score_confidence_assets,
        COUNT(*) FILTER (WHERE score_confidence = 'low') AS low_asset_score_confidence_assets,
        ROUND(AVG(COALESCE(bofu_strength_score, 0))::numeric, 1) AS avg_bofu_strength_score,
        COALESCE(SUM(proof_elements_count), 0) AS proof_elements_count,
        COALESCE(SUM(strong_proof_elements_count), 0) AS strong_proof_elements_count,
        COALESCE(SUM(weighted_proof_points), 0) AS weighted_proof_points
    FROM v_content_quality
    GROUP BY competitor_id
),
scored AS (
    SELECT
        c.id AS competitor_id,
        c.name AS competitor_name,
        COALESCE(sa.valid_assets, 0) AS valid_assets,
        COALESCE(sa.extraction_eligible_assets, 0) AS extraction_eligible_assets,
        COALESCE(sa.insight_pages, 0) AS insight_pages,
        COALESCE(sa.insight_pages::FLOAT / NULLIF(sa.extraction_eligible_assets, 0), 0) AS insight_coverage,
        COALESCE(qs.avg_content_quality_score, 0) AS avg_content_quality_score,
        COALESCE(qs.avg_content_depth_score, 0) AS avg_content_depth_score,
        COALESCE(qs.avg_metadata_completeness_score, 0) AS avg_metadata_completeness_score,
        COALESCE(qs.high_asset_score_confidence_assets, 0) AS high_asset_score_confidence_assets,
        COALESCE(qs.medium_asset_score_confidence_assets, 0) AS medium_asset_score_confidence_assets,
        COALESCE(qs.low_asset_score_confidence_assets, 0) AS low_asset_score_confidence_assets,
        COALESCE(qs.avg_bofu_strength_score, 0) AS avg_bofu_strength_score,
        COALESCE(qs.proof_elements_count, 0) AS proof_elements_count,
        COALESCE(qs.strong_proof_elements_count, 0) AS strong_proof_elements_count,
        COALESCE(qs.weighted_proof_points, 0) AS weighted_proof_points,
        COALESCE(qs.proof_elements_count::FLOAT / NULLIF(sa.valid_assets, 0), 0) AS proof_elements_per_valid_asset,
        COALESCE(qs.strong_proof_elements_count::FLOAT / NULLIF(sa.valid_assets, 0), 0) AS strong_proof_elements_per_valid_asset,
        COALESCE(qs.weighted_proof_points::FLOAT / NULLIF(sa.valid_assets, 0), 0) AS weighted_proof_points_per_valid_asset,
        CASE
            WHEN COALESCE(qs.strong_proof_elements_count, 0) = 0
                THEN COALESCE(qs.proof_elements_count, 0) * 12
            ELSE COALESCE(qs.proof_elements_count, 0) * 25
        END AS weighted_proof_points_max_plausible
    FROM competitors c
    LEFT JOIN scorecard_assets sa ON sa.competitor_id = c.id
    LEFT JOIN quality_scores qs ON qs.competitor_id = c.id
)
SELECT
    scored.competitor_id,
    scored.competitor_name,
    scored.valid_assets,
    scored.insight_pages,
    scored.insight_coverage,
    scored.avg_content_quality_score,
    scored.avg_content_depth_score,
    scored.avg_metadata_completeness_score,
    scored.avg_bofu_strength_score,
    scored.proof_elements_per_valid_asset,
    CASE
        WHEN scored.valid_assets < 3 THEN 'low'
        WHEN scored.insight_coverage < 0.80 THEN 'low'
        WHEN scored.extraction_eligible_assets >= 5 AND scored.insight_coverage >= 0.90 THEN 'high'
        ELSE 'medium'
    END AS score_confidence,
    CASE
        WHEN scored.valid_assets < 3 THEN 'sample confidence low: fewer than 3 valid assets, even if extraction coverage is complete'
        WHEN scored.insight_coverage < 0.80 THEN 'sample confidence low: extraction coverage below 80 percent of valid assets'
        WHEN scored.extraction_eligible_assets >= 5 AND scored.insight_coverage >= 0.90 THEN 'sample confidence high: 5+ extraction-eligible assets with 90 percent+ extraction coverage'
        ELSE 'sample confidence medium: valid assets and extraction coverage are usable but limited'
    END AS confidence_reason,
    scored.proof_elements_count,
    scored.strong_proof_elements_count,
    scored.weighted_proof_points,
    CASE
        WHEN scored.valid_assets < 3
             AND scored.strong_proof_elements_per_valid_asset >= 0 THEN 0
        ELSE scored.strong_proof_elements_per_valid_asset
    END AS strong_proof_elements_per_valid_asset,
    scored.weighted_proof_points_per_valid_asset,
    scored.weighted_proof_points_max_plausible,
    CASE
        WHEN weighted_proof_points_per_valid_asset > 100
            THEN 'out_of_scale'
        WHEN strong_proof_elements_count = 0
             AND weighted_proof_points > weighted_proof_points_max_plausible
            THEN 'unreliable'
        ELSE 'valid'
    END AS weighted_proof_points_validation_status,
    CASE
        WHEN weighted_proof_points_per_valid_asset > 100
            THEN 'out_of_range: weighted proof points per valid asset exceeds 100'
        WHEN strong_proof_elements_count = 0
             AND weighted_proof_points > weighted_proof_points_max_plausible
            THEN 'unreliable: zero strong proof but weighted proof exceeds max plausible weak/medium evidence'
        ELSE 'valid: weighted proof is within plausible range'
    END AS weighted_proof_points_validation_reason,
    scored.high_asset_score_confidence_assets,
    scored.medium_asset_score_confidence_assets,
    scored.low_asset_score_confidence_assets,
    scored.extraction_eligible_assets
FROM scored;

CREATE OR REPLACE VIEW v_best_content_assets AS
SELECT *
FROM v_content_quality
WHERE is_valid_content_asset = TRUE
ORDER BY content_quality_score DESC, raw_page_id
LIMIT 25;

CREATE OR REPLACE VIEW v_weak_content_assets AS
SELECT *
FROM v_content_quality
WHERE is_valid_content_asset = TRUE
ORDER BY content_quality_score ASC, raw_page_id
LIMIT 25;

CREATE OR REPLACE VIEW v_opportunity_backlog AS
WITH quality_gap_clusters AS (
    SELECT
        asset_type AS related_topic,
        COUNT(DISTINCT competitor_id) AS competitor_prevalence,
        COUNT(DISTINCT url) AS source_count,
        ROUND(AVG(content_quality_score)::numeric, 1) AS avg_quality_score,
        MIN(content_quality_score) AS weakest_quality_score,
        jsonb_agg(DISTINCT url) FILTER (WHERE url IS NOT NULL) AS source_urls
    FROM v_content_quality
    WHERE content_quality_score < 50
      AND is_valid_content_asset = TRUE
      AND NULLIF(url, '') IS NOT NULL
    GROUP BY asset_type
    HAVING COUNT(DISTINCT competitor_id) >= 2
        OR COUNT(DISTINCT url) >= 3
),
topic_gaps AS (
    SELECT
        tg.controlled_topic_id AS related_topic,
        tg.controlled_topic_label,
        tg.gap_reason,
        tg.label_confidence,
        tg.topic_saturation,
        tg.gap_analysis_status,
        tg.gap_analysis_reason,
        tg.owned_sample_confidence,
        tg.owned_valid_assets,
        COUNT(DISTINCT tc.competitor_id) AS competitor_prevalence,
        CASE
            WHEN COUNT(*) FILTER (WHERE tc.funnel_stage = 'BOFU') > 0 THEN 'BOFU'
            WHEN COUNT(*) FILTER (WHERE tc.funnel_stage = 'MOFU') > 0 THEN 'MOFU'
            WHEN COUNT(*) FILTER (WHERE tc.funnel_stage = 'TOFU') > 0 THEN 'TOFU'
            ELSE 'unknown'
        END AS strongest_funnel_stage,
        COALESCE(
            jsonb_agg(DISTINCT source_url) FILTER (WHERE source_url IS NOT NULL),
            '[]'::jsonb
        ) AS source_urls,
        COUNT(DISTINCT source_url) FILTER (WHERE source_url IS NOT NULL) AS source_count
    FROM v_controlled_topic_gap tg
    JOIN v_controlled_topic_coverage tc
        ON tc.controlled_topic_id = tg.controlled_topic_id
    JOIN competitors c ON c.id = tc.competitor_id
    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(tc.source_urls, '[]'::jsonb)) AS source_url
    WHERE gap_reason = 'missing_on_owned_site'
      AND c.is_owned_domain = FALSE
      AND tg.label_confidence = 'normal'
      AND tg.topic_saturation <> 'low'
      AND tg.topic_saturation <> 'insufficient data'
      AND tg.controlled_topic_id <> 'unknown_other'
      AND lower(tg.controlled_topic_label) NOT LIKE '%%[low confidence]%%'
    GROUP BY
        tg.controlled_topic_id,
        tg.controlled_topic_label,
        tg.gap_reason,
        tg.label_confidence,
        tg.topic_saturation,
        tg.gap_analysis_status,
        tg.gap_analysis_reason,
        tg.owned_sample_confidence,
        tg.owned_valid_assets
),
pain_point_opportunities AS (
    SELECT
        pain_point AS related_topic,
        competitors_mentioning_it AS competitor_prevalence,
        jsonb_array_length(COALESCE(source_urls, '[]'::jsonb)) AS source_count,
        COALESCE(source_urls, '[]'::jsonb) AS source_urls,
        explicit_frequency,
        inferred_from_benefit_frequency,
        keyword_fallback_frequency,
        inferred_source_count,
        weighted_evidence_score,
        evidence_mix,
        dominant_evidence_type,
        fallback_share,
        evidence_strength
    FROM v_pain_point_coverage
    WHERE competitors_mentioning_it >= 2
      AND jsonb_array_length(COALESCE(source_urls, '[]'::jsonb)) > 0
      AND NULLIF(pain_point, '') IS NOT NULL
      AND lower(pain_point) NOT IN ('not_found', 'none', 'unknown')
)
SELECT
    CASE
        WHEN qg.competitor_prevalence >= 3 OR qg.source_count >= 5 THEN 'medium'
        ELSE 'low'
    END AS priority,
    qg.related_topic,
    'repeated_weak_content_quality' AS gap_reason,
    CONCAT(
        qg.competitor_prevalence,
        ' competitors have weak ',
        qg.related_topic,
        ' assets; average quality score ',
        qg.avg_quality_score
    ) AS competitor_evidence,
    qg.related_topic AS suggested_asset_type,
    CASE
        WHEN qg.related_topic IN ('pricing', 'case_studies', 'comparison') THEN 'BOFU'
        WHEN qg.related_topic IN ('product', 'features', 'docs') THEN 'MOFU'
        ELSE 'TOFU'
    END AS suggested_funnel_stage,
    CASE
        WHEN qg.related_topic IN ('pricing', 'case_studies', 'comparison') THEN 'book demo'
        WHEN qg.related_topic IN ('product', 'features') THEN 'view pricing'
        ELSE 'download guide'
    END AS suggested_cta,
    qg.source_urls,
    'repeated_competitor_weakness' AS evidence_strength,
    qg.source_count,
    CASE
        WHEN qg.competitor_prevalence >= 3 OR qg.source_count >= 5 THEN 'medium'
        ELSE 'low'
    END AS confidence,
    'Repeated weak competitor pages point to a content quality gap the owned site can exploit with stronger evidence, clearer structure, or a more decisive CTA.' AS why_now,
    'none'::text AS blocked_by,
    qg.competitor_prevalence,
    CASE
        WHEN qg.related_topic IN ('pricing', 'case_studies', 'comparison') THEN 'high'
        WHEN qg.related_topic IN ('product', 'features', 'docs') THEN 'medium'
        ELSE 'low'
    END AS funnel_importance,
    'not_evaluated_without_owned_gap' AS owned_gap_status,
    CASE
        WHEN qg.competitor_prevalence >= 3 OR qg.source_count >= 5 THEN 'medium'
        ELSE 'low'
    END AS sample_confidence,
    'exploit_repeated_competitor_weakness' AS recommended_action_type,
    NULL::text AS evidence_mix,
    NULL::numeric AS weighted_evidence_score,
    NULL::text AS dominant_evidence_type,
    NULL::numeric AS fallback_share,
    'not_evaluated_without_owned_gap' AS gap_analysis_status,
    'owned-domain comparison is not part of repeated quality weakness clustering' AS gap_analysis_reason
FROM quality_gap_clusters qg
UNION ALL
SELECT
    CASE
        WHEN tg.gap_analysis_status = 'directional_only' THEN 'medium'
        WHEN tg.competitor_prevalence >= 2 AND tg.source_count >= 2 THEN 'high'
        ELSE 'medium'
    END AS priority,
    tg.controlled_topic_label AS related_topic,
    tg.gap_reason,
    CONCAT(
        tg.competitor_prevalence,
        ' competitors cover this topic while the owned domain does not.'
    ) AS competitor_evidence,
    CASE
        WHEN tg.strongest_funnel_stage = 'BOFU' THEN 'comparison'
        WHEN tg.strongest_funnel_stage = 'MOFU' THEN 'product'
        ELSE 'guide'
    END AS suggested_asset_type,
    tg.strongest_funnel_stage AS suggested_funnel_stage,
    CASE
        WHEN tg.strongest_funnel_stage = 'BOFU' THEN 'book demo'
        WHEN tg.strongest_funnel_stage = 'MOFU' THEN 'view pricing'
        ELSE 'download guide'
    END AS suggested_cta,
    tg.source_urls,
    CASE
        WHEN tg.competitor_prevalence >= 2 THEN 'multiple_competitor_sources'
        ELSE 'single_competitor_source'
    END AS evidence_strength,
    tg.source_count,
    CASE
        WHEN tg.gap_analysis_status = 'directional_only' THEN 'medium'
        WHEN tg.competitor_prevalence >= 2 AND tg.source_count >= 2 THEN 'high'
        ELSE 'medium'
    END AS confidence,
    'Owned-domain comparison is configured and competitors cover this topic with source evidence.' AS why_now,
    CASE
        WHEN tg.gap_analysis_status = 'directional_only' THEN tg.gap_analysis_reason
        ELSE 'none'
    END AS blocked_by,
    tg.competitor_prevalence,
    CASE
        WHEN tg.strongest_funnel_stage = 'BOFU' THEN 'high'
        WHEN tg.strongest_funnel_stage = 'MOFU' THEN 'medium'
        ELSE 'low'
    END AS funnel_importance,
    tg.gap_analysis_status AS owned_gap_status,
    CASE
        WHEN tg.gap_analysis_status = 'directional_only' THEN 'medium'
        WHEN tg.competitor_prevalence >= 3 OR tg.source_count >= 5 THEN 'high'
        WHEN tg.competitor_prevalence >= 2 OR tg.source_count >= 2 THEN 'medium'
        ELSE 'low'
    END AS sample_confidence,
    'fill_owned_topic_gap' AS recommended_action_type,
    NULL::text AS evidence_mix,
    NULL::numeric AS weighted_evidence_score,
    NULL::text AS dominant_evidence_type,
    NULL::numeric AS fallback_share,
    tg.gap_analysis_status,
    tg.gap_analysis_reason
FROM topic_gaps tg
WHERE tg.source_count > 0
UNION ALL
SELECT
    CASE
        WHEN ppo.evidence_strength = 'fallback_only' THEN 'low'
        WHEN ppo.fallback_share >= 0.5 THEN 'low'
        WHEN ppo.evidence_strength = 'explicit_heavy'
             AND ppo.competitor_prevalence >= 3
             AND ppo.explicit_frequency >= 1
             AND ppo.weighted_evidence_score >= 8 THEN CONCAT('h', 'igh')
        WHEN ppo.explicit_frequency >= 1
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        WHEN ppo.inferred_source_count >= 2
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        ELSE 'low'
    END AS priority,
    ppo.related_topic,
    'repeated_pain_point' AS gap_reason,
    CONCAT(
        ppo.competitor_prevalence,
        ' competitors mention this pain point.'
    ) AS competitor_evidence,
    'comparison' AS suggested_asset_type,
    'MOFU' AS suggested_funnel_stage,
    'book demo' AS suggested_cta,
    ppo.source_urls,
    CONCAT('repeated_competitor_pain_point:', ppo.evidence_strength) AS evidence_strength,
    ppo.source_count,
    CASE
        WHEN ppo.evidence_strength = 'fallback_only' THEN 'low'
        WHEN ppo.fallback_share >= 0.5 THEN 'low'
        WHEN ppo.evidence_strength = 'explicit_heavy'
             AND ppo.competitor_prevalence >= 3
             AND ppo.explicit_frequency >= 1
             AND ppo.weighted_evidence_score >= 8 THEN CONCAT('h', 'igh')
        WHEN ppo.explicit_frequency >= 1
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        WHEN ppo.inferred_source_count >= 2
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        ELSE 'low'
    END AS confidence,
    CASE
        WHEN ppo.evidence_strength = 'fallback_only' THEN
            'Repeated pain-point pattern is visible, but all evidence is keyword fallback and should be treated as weak support.'
        WHEN ppo.fallback_share >= 0.5 THEN
            'Repeated pain-point pattern is mostly fallback evidence, so confidence is downgraded until explicit evidence supports it.'
        ELSE
            'Repeated pain-point evidence across competitors can support sharper owned positioning and proof-led content.'
    END AS why_now,
    CASE
        WHEN ppo.evidence_strength = 'fallback_only' THEN 'fallback_only pain-point evidence'
        WHEN ppo.fallback_share >= 0.5 THEN 'mostly fallback pain-point evidence'
        ELSE 'none'
    END AS blocked_by,
    ppo.competitor_prevalence,
    'medium' AS funnel_importance,
    'not_evaluated_without_owned_gap' AS owned_gap_status,
    CASE
        WHEN ppo.evidence_strength = 'fallback_only' THEN 'low'
        WHEN ppo.fallback_share >= 0.5 THEN 'low'
        WHEN ppo.evidence_strength = 'explicit_heavy'
             AND ppo.competitor_prevalence >= 3
             AND ppo.explicit_frequency >= 1
             AND ppo.weighted_evidence_score >= 8 THEN CONCAT('h', 'igh')
        WHEN ppo.explicit_frequency >= 1
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        WHEN ppo.inferred_source_count >= 2
             AND ppo.competitor_prevalence >= 2 THEN 'medium'
        ELSE 'low'
    END AS sample_confidence,
    'address_repeated_pain_point' AS recommended_action_type,
    ppo.evidence_mix,
    ppo.weighted_evidence_score,
    ppo.dominant_evidence_type,
    ppo.fallback_share,
    'not_evaluated_without_owned_gap' AS gap_analysis_status,
    'owned-domain comparison is not part of pain-point clustering' AS gap_analysis_reason
FROM pain_point_opportunities ppo;

CREATE OR REPLACE VIEW v_core_dataset_reliability AS
WITH configured AS (
    SELECT
        competitor_id,
        COUNT(*) AS configured_urls
    FROM source_urls
    GROUP BY competitor_id
),
crawl_status AS (
    SELECT
        competitor_id,
        COUNT(*) FILTER (WHERE success = TRUE) AS crawled_ok_pages,
        COUNT(*) FILTER (WHERE success = FALSE) AS failed_pages
    FROM raw_pages
    GROUP BY competitor_id
),
validity AS (
    SELECT
        competitor_id,
        COUNT(*) FILTER (WHERE is_valid_content_asset = TRUE) AS valid_assets,
        COUNT(*) FILTER (
            WHERE is_valid_content_asset = TRUE
               OR validity_reason = 'missing_insight'
        ) AS extraction_eligible_assets,
        COUNT(*) FILTER (WHERE is_valid_content_asset = FALSE) AS invalid_or_non_evaluable,
        COUNT(*) FILTER (
            WHERE is_valid_content_asset = TRUE
              AND has_insight = TRUE
        ) AS insight_pages
    FROM v_content_asset_validity
    GROUP BY competitor_id
)
SELECT
    c.id AS competitor_id,
    c.name AS competitor_name,
    COALESCE(configured.configured_urls, 0) AS configured_urls,
    COALESCE(crawl_status.crawled_ok_pages, 0) AS crawled_ok_pages,
    COALESCE(crawl_status.failed_pages, 0) AS failed_pages,
    COALESCE(validity.valid_assets, 0) AS valid_assets,
    COALESCE(validity.invalid_or_non_evaluable, 0) AS invalid_or_non_evaluable,
    COALESCE(validity.insight_pages, 0) AS insight_pages,
    COALESCE(validity.insight_pages::FLOAT / NULLIF(validity.extraction_eligible_assets, 0), 0) AS insight_coverage,
    COALESCE(scorecards.score_confidence, 'low') AS sample_confidence,
    COALESCE(scorecards.confidence_reason, 'sample confidence low: no valid analytical assets are available') AS sample_confidence_reason,
    COALESCE(scorecards.high_asset_score_confidence_assets, 0) AS high_asset_score_confidence_assets,
    COALESCE(scorecards.medium_asset_score_confidence_assets, 0) AS medium_asset_score_confidence_assets,
    COALESCE(scorecards.low_asset_score_confidence_assets, 0) AS low_asset_score_confidence_assets,
    COALESCE(validity.extraction_eligible_assets, 0) AS extraction_eligible_assets
FROM competitors c
LEFT JOIN configured ON configured.competitor_id = c.id
LEFT JOIN crawl_status ON crawl_status.competitor_id = c.id
LEFT JOIN validity ON validity.competitor_id = c.id
LEFT JOIN v_competitor_scorecards scorecards ON scorecards.competitor_id = c.id;

CREATE OR REPLACE VIEW v_core_competitor_scorecards AS
SELECT *
FROM v_competitor_scorecards;

CREATE OR REPLACE VIEW v_core_content_quality AS
SELECT *
FROM v_content_quality
WHERE is_valid_content_asset = TRUE;

CREATE OR REPLACE VIEW v_core_funnel_mix AS
SELECT *
FROM v_funnel_mix;

CREATE OR REPLACE VIEW v_core_pain_point_positioning AS
SELECT
    pain_point,
    competitors_mentioning_it,
    frequency,
    source_urls,
    pain_point_categories,
    pain_point_evidence_types,
    explicit_frequency,
    inferred_from_benefit_frequency,
    keyword_fallback_frequency,
    weighted_evidence_score,
    evidence_mix,
    dominant_evidence_type,
    fallback_share,
    evidence_strength
FROM v_pain_point_coverage;

CREATE OR REPLACE VIEW v_core_proof_evidence AS
SELECT
    competitor_id,
    competitor_name,
    proof_elements_count,
    total_assets,
    proof_density,
    strong_proof_elements_count,
    weighted_proof_points,
    strong_proof_density,
    weighted_proof_points_per_asset
FROM v_proof_density;

CREATE OR REPLACE VIEW v_core_opportunity_backlog AS
SELECT *
FROM v_opportunity_backlog
WHERE recommended_action_type IN (
    'exploit_repeated_competitor_weakness',
    'fill_owned_topic_gap',
    'address_repeated_pain_point'
)
AND confidence <> 'not_evaluable';

CREATE OR REPLACE VIEW v_diagnostic_crawl_volume AS
SELECT
    competitor_id,
    competitor_name,
    pages_analyzed,
    crawled_ok_pages,
    total_words,
    share_of_voice AS crawled_word_share_proxy,
    valid_assets,
    valid_asset_words
FROM v_competitor_share_of_voice;

CREATE OR REPLACE VIEW v_diagnostic_topic_output AS
SELECT
    trends.competitor_id,
    trends.competitor_name,
    trends.topic_id,
    trends.topic_label,
    trends.topic_probability,
    NULL::text AS funnel_stage,
    trends.source_type,
    trends.url,
    topic_meta.label_confidence,
    topic_meta.topic_saturation
FROM v_topic_trends trends
LEFT JOIN (
    SELECT DISTINCT ON (topic_id, competitor_id)
        topic_id,
        competitor_id,
        label_confidence,
        topic_saturation
    FROM v_topic_share
    ORDER BY topic_id, competitor_id
) topic_meta
    ON topic_meta.topic_id = trends.topic_id
   AND topic_meta.competitor_id = trends.competitor_id;

CREATE OR REPLACE VIEW v_diagnostic_invalid_assets AS
SELECT
    raw_page_id,
    competitor_id,
    competitor_name,
    url,
    source_type,
    title,
    word_count,
    has_insight,
    asset_validity_status,
    is_valid_content_asset,
    validity_reason,
    recommended_action
FROM v_data_quality_issues;

CREATE OR REPLACE VIEW v_diagnostic_cta_coverage AS
SELECT
    competitor_id,
    competitor_name,
    'any_cta_coverage' AS diagnostic_metric,
    any_cta_coverage AS diagnostic_value,
    pages_with_any_cta AS diagnostic_count,
    total_insight_pages,
    sample_confidence,
    NULL::text AS cta_type
FROM v_cta_coverage_by_competitor
UNION ALL
SELECT
    competitor_id,
    competitor_name,
    'conversion_cta_coverage' AS diagnostic_metric,
    conversion_cta_coverage AS diagnostic_value,
    pages_with_conversion_cta AS diagnostic_count,
    total_insight_pages,
    sample_confidence,
    NULL::text AS cta_type
FROM v_cta_coverage_by_competitor
UNION ALL
SELECT
    competitor_id,
    competitor_name,
    'cta_type_share' AS diagnostic_metric,
    cta_type_share AS diagnostic_value,
    cta_type_count AS diagnostic_count,
    NULL::integer AS total_insight_pages,
    NULL::text AS sample_confidence,
    cta_type
FROM v_cta_type_mix_by_competitor;

CREATE OR REPLACE VIEW v_diagnostic_sentiment AS
SELECT
    competitor_id,
    competitor_name,
    total_insights,
    positive_count,
    negative_count,
    neutral_count,
    mixed_count,
    not_found_count,
    positive_share,
    negative_share,
    neutral_share,
    mixed_share,
    not_found_share
FROM v_competitor_sentiment;

COMMENT ON VIEW v_core_dataset_reliability IS 'Core KPI view for dataset and evidence reliability; use for Superset dashboard interpretation confidence.';
COMMENT ON VIEW v_core_competitor_scorecards IS 'Core KPI view for competitor scorecards using valid analytical assets, sample confidence, and asset score confidence distribution.';
COMMENT ON VIEW v_core_content_quality IS 'Core KPI view for valid analytical asset quality; excludes invalid and non-evaluable assets.';
COMMENT ON VIEW v_core_funnel_mix IS 'Core KPI view for funnel-stage coverage over valid analytical assets.';
COMMENT ON VIEW v_core_pain_point_positioning IS 'Core KPI view for weighted pain point positioning with evidence mix and source URLs.';
COMMENT ON VIEW v_core_proof_evidence IS 'Core KPI view for normalized and deduplicated proof evidence quality.';
COMMENT ON VIEW v_core_opportunity_backlog IS 'Core KPI view for actionable content opportunities backed by reliable inputs.';
COMMENT ON VIEW v_diagnostic_crawl_volume IS 'Diagnostic view for crawl volume, raw word counts, and crawled word share proxy; not market share or strategic KPI.';
COMMENT ON VIEW v_diagnostic_topic_output IS 'Diagnostic view for raw topic modeling output and topic confidence; topic labels are not strategic KPI until promoted by quality gates.';
COMMENT ON VIEW v_diagnostic_invalid_assets IS 'Diagnostic view for invalid, thin, placeholder, missing-insight, or otherwise non-evaluable assets.';
COMMENT ON VIEW v_diagnostic_cta_coverage IS 'Diagnostic view for current CTA coverage and CTA class mix; generic CTA coverage is not strategic KPI.';
COMMENT ON VIEW v_diagnostic_sentiment IS 'Diagnostic view for extracted sentiment shares; sentiment is not a strategic KPI.';
COMMENT ON VIEW v_competitor_share_of_voice IS 'Legacy compatibility diagnostic for crawled word share proxy; not market share and not strategic KPI.';
COMMENT ON VIEW v_competitor_sentiment IS 'Legacy compatibility diagnostic for extracted sentiment shares; not strategic KPI.';
COMMENT ON VIEW v_cta_intelligence IS 'Legacy compatibility diagnostic for generic CTA coverage; not strategic KPI.';
COMMENT ON VIEW v_topic_trends IS 'Legacy compatibility diagnostic for raw topic assignments; not strategic KPI.';
COMMENT ON VIEW v_topic_coverage IS 'Topic diagnostic view gated to valid assets; not a core strategic KPI while topic labels remain unstable.';
COMMENT ON VIEW v_topic_share IS 'Topic diagnostic view with label confidence and saturation; not a core strategic KPI while labels remain unstable.';
COMMENT ON VIEW v_controlled_topic_coverage IS 'Strategic controlled topic coverage over valid analytical assets using the config-backed taxonomy.';
COMMENT ON VIEW v_controlled_topic_gap IS 'Strategic controlled topic owned-site gap view with owned-domain sample confidence gating.';
