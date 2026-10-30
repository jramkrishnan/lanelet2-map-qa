-- Lanelets within 30 m of a traffic light, nearest first.
-- Traffic lights are the boundaries whose type is 'traffic_light'.
SELECT
    l.lanelet_id,
    b.linestring_id                                      AS traffic_light_id,
    ROUND(ST_Distance(l.geom::geography, b.geom::geography)::numeric, 1) AS distance_m
FROM lanelets l
JOIN boundaries b
  ON b.type = 'traffic_light'
 AND ST_DWithin(l.geom::geography, b.geom::geography, 30)
ORDER BY distance_m;
