# Excise tax definitions: (HSN code, rate)
EXCISE_TAX_DEFINITIONS = [
    (1012100, 12.0),
    (2011000, 5.0),
    (3038900, 5.0),
    (4022100, 12.0),
    (5010000, 5.0),
    (6029000, 18.0),
    (7020000, 5.0),
    (8052010, 10.0),
    (9011110, 5.0),
    (10061010, 0.0),
    (11010000, 5.0),
    (12074000, 5.0),
    (13021919, 12.0),
    (14049010, 5.0),
    (15071000, 5.0),
    (17019990, 18.0),
    (18050000, 5.0),
    (19053100, 18.0),
    (20081100, 12.0),
    (21069099, 18.0),
]


def _migrate_einvoice_counters(env):
    """Attach legacy company-only counters to the first config per company."""
    Counter = env['einvoice.counter'].sudo()
    Config = env['einvoice.config'].sudo()
    for counter in Counter.search([]):
        if counter.config_id:
            continue
        config = Config.search([('company_id', '=', counter.company_id.id)], limit=1)
        if not config:
            continue
        existing = Counter.search([('config_id', '=', config.id)], limit=1)
        if existing and existing.id != counter.id:
            counter.unlink()
        else:
            counter.write({'config_id': config.id})


def post_init_hook(env):
    """Create Excise tax group and migrate fiscal counters."""
    _migrate_einvoice_counters(env)
    country_et = env.ref('base.et', raise_if_not_found=False)
    if not country_et:
        return
    main_company = env.ref('base.main_company', raise_if_not_found=False)
    if not main_company or main_company.account_fiscal_country_id != country_et:
        return
    companies = main_company
    TaxGroup = env['account.tax.group']
    Tax = env['account.tax']
    for company in companies:
        # Consider both company-specific and shared (company_id=False) Excise group
        existing_group = TaxGroup.search([
            ('country_id', '=', country_et.id),
            ('name', '=', 'Excise'),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], limit=1)
        if not existing_group:
            with env.cr.savepoint():
                existing_group = TaxGroup.create({
                    'name': 'Excise',
                    'country_id': country_et.id,
                    'company_id': company.id,
                })
        group = existing_group
        for hsn, rate in EXCISE_TAX_DEFINITIONS:
            name = f'Excise {hsn} {rate}'
            if Tax.search([('name', '=', name), ('company_id', '=', company.id)], limit=1):
                continue
            with env.cr.savepoint():
                Tax.create({
                    'name': name,
                    'amount': rate,
                    'amount_type': 'percent',
                    'type_tax_use': 'sale',
                    'tax_group_id': group.id,
                    'company_id': company.id,
                })
