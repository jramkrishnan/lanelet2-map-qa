-- Issues per lanelet across all faulty runs, split by check.
-- Issues are linked to lanelets by primitive_id. Issues on regulatory elements have no
-- lanelet, so they are listed separately with lanelet_id NULL.
SELECT
    l.lanelet_id,
    f.check,
    COUNT(*)                      AS issues,
    COUNT(DISTINCT f.trial_id)    AS trials_affected
FROM faulty_issues f
LEFT JOIN lanelets l ON l.lanelet_id = f.primitive_id
GROUP BY l.lanelet_id, f.check
ORDER BY l.lanelet_id NULLS LAST, issues DESC;
