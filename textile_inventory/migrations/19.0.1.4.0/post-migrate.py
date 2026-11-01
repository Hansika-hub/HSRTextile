def migrate(cr, version):
    """Production entries used a single 'worker_id'. Move it into the new
    worker list (the worker gets all the good metres), then drop the old
    column (it is NOT NULL and would block new entries)."""
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'textile_production' AND column_name = 'worker_id'")
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO textile_production_worker
            (production_id, worker_id, share_metres, date, shift, loom_id,
             order_id, production_state, create_uid, write_uid,
             create_date, write_date)
        SELECT p.id, p.worker_id,
               CASE WHEN p.state = 'confirmed' THEN p.good_metres ELSE 0 END,
               p.date, p.shift, p.loom_id, p.order_id, p.state,
               p.create_uid, p.write_uid, now(), now()
        FROM textile_production p
        WHERE p.worker_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM textile_production_worker w
                          WHERE w.production_id = p.id AND w.worker_id = p.worker_id)
    """)
    cr.execute("ALTER TABLE textile_production DROP COLUMN worker_id")
