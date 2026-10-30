-- Total mapped lane length, measured along each lanelet's centerline.
-- Casting to geography makes ST_Length return meters on the WGS84 ellipsoid.
SELECT
    COUNT(*)                                        AS lanelets,
    ROUND(SUM(ST_Length(geom::geography))::numeric, 1) AS total_length_m
FROM centerlines;
