-- Issue density per 100 m of lane, per lanelet, across all faulty runs.
-- Lane length comes from the centerline (in meters, via geography).
SELECT
    c.lanelet_id,
    ROUND(ST_Length(c.geom::geography)::numeric, 1)               AS length_m,
    COUNT(f.primitive_id)                                                     AS issues,
    ROUND((COUNT(f.primitive_id) / (ST_Length(c.geom::geography) / 100))::numeric, 1) AS issues_per_100m
FROM centerlines c
LEFT JOIN faulty_issues f ON f.primitive_id = c.lanelet_id
GROUP BY c.lanelet_id, c.geom
ORDER BY issues_per_100m DESC;
