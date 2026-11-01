def migrate(cr, version):
    """Give old yarn receipts a clear legacy number and their real date."""
    cr.execute(
        "UPDATE textile_yarn_bag_line "
        "SET name = 'YRN/LEGACY/' || id WHERE name = 'New'"
    )
    cr.execute(
        "UPDATE textile_yarn_bag_line "
        "SET date = create_date::date WHERE create_date IS NOT NULL"
    )
