{
    'name': 'Textile Inventory',
    'version': '19.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Textile inventory management',
    'depends': [
        'base',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/stock_locations.xml',
	'data/pavu_sequence.xml',
	'data/fabric_sequence.xml',
        'views/yarn_bag_views.xml',
	 'views/pavu_production_views.xml',
	'views/fabric_production_views.xml',
    ],
    'installable': True,
    'application': True,

}
