"""Add N extra resident vehicles to the seeded society, to measure a bigger society.

    uv run python add_vehicles.py 420     # 80 seeded + 420 = 500 vehicles
"""

import os
import random
import sys
import uuid

import psycopg

URL = os.environ.get(
    "LOADTEST_DATABASE_URL", "postgresql://gatesense@127.0.0.1:5432/gatesense"
)
count = int(sys.argv[1])
rng = random.Random(7)
with psycopg.connect(URL) as conn:
    society_id, flat_ids = None, []
    for society, flat in conn.execute("SELECT society_id, id FROM flats"):
        society_id = society
        flat_ids.append(flat)
    existing = {p for (p,) in conn.execute("SELECT plate_normalized FROM vehicles")}
    rows = []
    while len(rows) < count:
        letters = "".join(rng.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=2))
        plate = f"UP{rng.randint(11, 99)}{letters}{rng.randint(1000, 9999)}"
        if plate in existing:
            continue
        existing.add(plate)
        rows.append((uuid.uuid4(), society_id, rng.choice(flat_ids), plate, plate))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO vehicles (id, society_id, flat_id, plate_raw, plate_normalized,"
            " vehicle_type, is_active, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, 'car', true, now(), now())",
            rows,
        )
print(f"added {count} vehicles")
