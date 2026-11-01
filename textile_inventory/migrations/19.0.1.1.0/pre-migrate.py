def migrate(cr, version):
    """The old Pavu 'production' model (yarn -> Pavu) was wrong for this
    business: Pavu is supplied by the vendor. Keep its test data under a
    legacy name instead of deleting it."""
    cr.execute("SELECT to_regclass('textile_pavu_production')")
    if cr.fetchone()[0]:
        cr.execute(
            "ALTER TABLE textile_pavu_production "
            "RENAME TO textile_pavu_production_legacy"
        )
