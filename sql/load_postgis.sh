#!/usr/bin/env bash
# Start a PostGIS container, load outputs/map_qa.gpkg into it, and run every query in sql/.
# Run from the repo root: bash sql/load_postgis.sh   (stop it later: docker rm -f josm-postgis)
set -euo pipefail

docker network create josm-net >/dev/null 2>&1 || true
if ! docker ps --format '{{.Names}}' | grep -q '^josm-postgis$'; then
    docker run -d --name josm-postgis --network josm-net --platform linux/amd64 \
        -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgis/postgis:16-3.4 >/dev/null
fi
# Check over TCP, not the local socket: during first-time setup the image runs a temporary
# socket-only server, which would report "ready" before the real one is up.
until docker exec josm-postgis pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done

# ogr2ogr (from the GDAL image) copies every GeoPackage layer into a table of the same name.
docker run --rm --network josm-net --platform linux/amd64 -v "$PWD":/work \
    ghcr.io/osgeo/gdal:ubuntu-small-3.9.2 \
    ogr2ogr -f PostgreSQL "PG:host=josm-postgis user=postgres password=postgres dbname=postgres" \
    /work/outputs/map_qa.gpkg -overwrite -lco GEOMETRY_NAME=geom -nlt PROMOTE_TO_MULTI

for query in sql/0*.sql; do
    echo "== $query"
    docker exec -i josm-postgis psql -U postgres -q < "$query"
done
