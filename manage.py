from playhouse.migrate import MySQLMigrator, migrate
from main import (
    BooleanField,
    Brand,
    CliApp,
    Customer,
    db,
    PriceChange,
    Product,
    SmsQueue,
    Subscription,
)
import os
import sys


SENDING_LIST = 'conf/app.conf'
KNOWN_LIST = 'conf/user.list'


def get_list(filename):
    '''Get list of brand and numbers for that brand
    '''
    brand_sending_map = {}
    brand = None
    for line in open(os.path.join(os.path.dirname(__file__), filename)):
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            brand = line[1:-1]
            brand_sending_map[brand] = []
        elif line.startswith('+') and line[1:].isdigit():
            brand_sending_map[brand].append(line)
    return brand_sending_map


def migrate():
    Brand.create_table()
    Customer.create_table()
    Product.create_table()
    PriceChange.create_table()
    SmsQueue.create_table()
    Subscription.create_table()

    # migrator = MySQLMigrator(db)


def populate():
    sending_list = get_list(SENDING_LIST)
    welcomed_list = get_list(KNOWN_LIST)

    brands = {b.name: b for b in Brand.select()}
    customers = {c.number: c for c in Customer.select()}
    subscriptions = {(s.brand_id, s.customer_id): s for s in Subscription.select()}

    with db.atomic():
        for lst in [sending_list, welcomed_list]:
            for brand, recipients in lst.items():
                # Create brands
                if brand not in brands:
                    brands[brand] = Brand.create(name=brand)

                # Create customers
                for recipient in recipients:
                    if recipient not in customers:
                        customers[recipient] = Customer.create(number=recipient)

        # Create subscriptions
        for brand, recipients in sending_list.items():
            for recipient in recipients:
                if (brand, recipient) not in subscriptions:
                    subscriptions[(brand, recipient)] = Subscription.create(brand_id=brand, customer_id=recipient, is_subscribed=True)

        for brand, recipients in welcomed_list.items():
            for recipient in recipients:
                if (brand, recipient) in subscriptions:
                    subscription = subscriptions[(brand, recipient)]
                    subscription.has_welcome = True
                    subscription.save()
                else:
                    subscriptions[(brand, recipient)] = Subscription.create(brand_id=brand, customer_id=recipient, has_welcome=True, is_subscribed=False)

        # Create products
        app = CliApp()
        for brand in brands:
            app.refresh_for(brand)


def populate_images():
    app = CliApp()
    for brand in Brand.select():
        for scrapper_cls in app.scrappers:
            scrapper = scrapper_cls()
            products_soup = scrapper.soup(brand.name)
            with db.atomic():
                for product_soup in products_soup:
                    product = scrapper.product(product_soup)
                    try:
                        Product.update(image=product.image).where(Product.id==product.id).execute()
                    except Exception as e:
                        print(product, e)


if __name__ == "__main__":
    if 'migrate' in sys.argv:
        migrate()
    elif 'populate' in sys.argv:
        populate()
    elif 'images' in sys.argv:
        populate_images()
    else:
        print(
            "Usage:\n\n"
            "manage.py COMMAND\n\n"
            "Where commands can be:\n"
            "images     : Repopulate product images\n"
            "migrate    : Create database tables\n"
            "populate   : Insert initial brands, customers and products\n"
        )
