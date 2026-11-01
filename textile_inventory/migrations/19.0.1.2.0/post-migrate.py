def migrate(cr, version):
    """The free-text order_ref on receipts is replaced by a link to a real
    Vendor Order. Drop the old column only if nothing was stored in it."""
    for table in ('textile_yarn_bag_line', 'textile_pavu_receipt'):
        cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'order_ref'", (table,))
        if not cr.fetchone():
            continue
        cr.execute('SELECT count(*) FROM "%s" WHERE order_ref IS NOT NULL' % table)
        if cr.fetchone()[0] == 0:
            cr.execute('ALTER TABLE "%s" DROP COLUMN order_ref' % table)
