from bs4 import BeautifulSoup
from flask import (
    abort,
    flash,
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import FlaskForm
from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
    FloatField,
    fn,
    ForeignKeyField,
    IntegrityError,
    JOIN,
    Model,
    TextField,
)
from playhouse.db_url import connect
from twilio.rest import Client
from wtforms import fields as wtf, validators as wtfv, widgets as wtfw
import wtforms.widgets.html5 as wtfw5

import datetime
import functools
import json
import math
import os
import random
import requests
import sys
import time
import urllib.parse

# Configurations

WAIT_TIMEOUT = 900
# WAIT_TIMEOUT = 5
SMS_TIMEOUT = 10

WELCOME_MESSAGE = "Welkom bij alertje.nl. Je ontvangt updates van {brand}. Je kan nu inloggen op client.alertje.nl (overzicht prijsveranderingen) je wachtwoord is {password}"
UPDATE_MESSAGE = "Er zijn producten van prijs veranderd van {brands} Kijk nu via {url} en login met je telefoonnummer en wachtwoord: {password}."

# Live credentials
TWILIO_ACCOUNT_SID = 'AC275e9e09f6149794c88df0d3a3950df7'
TWILIO_AUTH_TOKEN = '2d82e32b4821161cb3fb560f9a7ddb51'
TWILIO_FROM_NUMBER = '+3197014201256'

# Test credentials
# TWILIO_ACCOUNT_SID = 'AC37f5dcfdb98923eca3c3412cc2d0fe31'
# TWILIO_AUTH_TOKEN = '3b62e7d8cebe1d2d35a9f501ac089d14'
# TWILIO_FROM_NUMBER = '+15005550006'

DB_URL = 'mysql://debijenkorf:M8uh4S1DvC@142.93.225.196/debijenkorf'
# DB_URL = 'mysql://debijenkorf:debijenkorf@localhost/debijenkorf'
VERBOSE = True


db = connect(DB_URL)


def log(status):
    if VERBOSE:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("{} {}".format(now, status), flush=True)


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'customer' in session:
            try:
                customer = Customer.get(Customer.number==session['customer'])
                request.customer = customer
                if customer.is_admin:
                    return f(*args, **kwargs)
            except Customer.DoesNotExist:
                pass
        return redirect(url_for('login', next=request.path))
    return wrapper


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'customer' in session:
            try:
                customer = Customer.get(Customer.number==session['customer'])
                request.customer = customer
                return f(*args, **kwargs)
            except Customer.DoesNotExist:
                pass
        return redirect(url_for('login', next=request.path))
    return wrapper


class Brand(Model):
    '''The product's brand
    '''
    name = CharField(primary_key=True)

    class Meta:
        database = db

    class Form(FlaskForm):
        name = wtf.StringField(validators=[wtfv.DataRequired()])

        def validate_name(self, field):
            if Brand.select().where(Brand.name==field.data).exists():
                raise wtfv.ValidationError('Brand already exists.')


class Product(Model):
    '''Representation of a product
    '''
    class Meta:
        database = db

    id = CharField(primary_key=True)
    brand = ForeignKeyField(Brand, backref='products', on_update='CASCADE', on_delete='CASCADE')
    name = CharField()
    image = CharField()
    description = TextField()
    discount = FloatField()
    price = FloatField()
    url = CharField()

    def merge(self, other_product, webshop):
        '''Merge in a product with new information
        '''
        price = self.price
        self.name = other_product.name
        self.description = other_product.description
        self.price = other_product.price
        if self._price_not_eq(price, other_product.price):
            PriceChange.create(product=self, price=other_product.price, webshop=webshop)
        self.save()

    def _price_not_eq(self, price1, price2):
        return not math.isclose(round(price1, 2), round(price2, 2))

    def __setattr__(self, name, value):
        '''Custom sanitization for url, price and discount fields
        '''
        if name == 'price' or name == 'discount':
            try:
                value = float(str(value).strip(' ,-%').replace(',','.'))
            except ValueError:
                value = 0
        elif name == 'url':
            value = urllib.parse.urlparse(value)
            id_value = value.path.replace('/', '')
            value = "{0.scheme}://{0.netloc}{0.path}".format(value)
            super(Product, self).__setattr__('id', id_value)
        super(Product, self).__setattr__(name, value)

    def __str__(self):
        return '{0.name} {0.description} ->{0.price}'.format(self)


class Customer(Model):
    '''Database model for users
    '''
    number = CharField(primary_key=True)
    password = CharField(null=True)
    is_admin = BooleanField(default=False)

    def update_message(self, brands):
        brands = "\n".join(str(b) for b in brands)
        return UPDATE_MESSAGE.format(brands=brands, url=self.url(), password=self.password)

    def url(self):
        return urllib.parse.urljoin("http://client.alertje.nl", self.number)

    def save(self, force_insert=False):
        if not self.password:
            self.password = self.gen_password()
        return super(Customer, self).save(force_insert=force_insert)

    def gen_password(self):
        return ''.join(str(random.randrange(0, 9)) for x in range(6))

    class Meta:
        database = db

    class Form(FlaskForm):
        number_validators = [wtfv.DataRequired(), wtfv.Regexp(r'^\+(\d{7,})', message='Invalid mobile number. +XXXXXXXXXXX required')]

        id = wtf.HiddenField()
        number = wtf.StringField(validators=number_validators, widget=wtfw5.TelInput())
        password = wtf.StringField(validators=[wtfv.Regexp(r'(\d{6,6}|)', message='Password is 6 digit number')])
        is_admin = wtf.BooleanField()

        def validate(self, *args, **kwargs):
            valid = super().validate(*args, **kwargs)
            if valid and not self.data['id'] and Customer.select().where(Customer.number==self.data['number']).exists():
                    self._errors = {'number': 'Customer already exists.'}
                    valid = False
            return valid

    class LoginForm(FlaskForm):
        number_validators = [wtfv.DataRequired(), wtfv.Regexp(r'^\+(\d{7,})', message='Invalid mobile number. +XXXXXXXXXXX required')]

        number = wtf.StringField(validators=number_validators, widget=wtfw5.TelInput())
        password = wtf.PasswordField(validators=[wtfv.DataRequired()])

        def validate(self, *args, **kwargs):
            valid = super(Customer.LoginForm, self).validate(*args, **kwargs)
            customer_exists = Customer.select().where(Customer.number==self.data['number']) \
                                .where(Customer.password==self.data['password']).exists()
            if valid and not customer_exists:
                valid = False
                self._errors = {'__extra__' :'Invalid number or password'}
            return valid


class Subscription(Model):
    '''Database model for users that have subscribed for a specific brand
    '''
    brand = ForeignKeyField(Brand, backref='subscriptions', on_update='CASCADE', on_delete='CASCADE')
    customer = ForeignKeyField(Customer, backref='subscriptions', on_update='CASCADE', on_delete='CASCADE')
    is_subscribed = BooleanField(default=False)
    has_welcome = BooleanField(default=False)

    def unsubscribe(self):
        self.is_subscribed = False
        self.save()

    def subscribe(self):
        if not self.is_subscribed:
            self.is_subscribed = True
        if not self.has_welcome:
            SmsQueue.queue(self.welcome_message(), self.customer_id)
            self.has_welcome = True
        self.save()

    def welcome(self):
        SmsQueue.queue(self.welcome_message(), self.customer_id)
        self.has_welcome = True
        self.save()

    def welcome_message(self):
        return WELCOME_MESSAGE.format(brand=self.brand_id, password=self.customer.password)

    @staticmethod
    def brands():
        brand_list = {}
        for subscription in Subscription.select(Subscription, Customer).join(Customer).where(Subscription.is_subscribed==True):
            if subscription.brand_id not in brand_list:
                brand_list[subscription.brand_id] = []
            brand_list[subscription.brand_id].append(subscription.customer)
        return brand_list

    class Meta:
        database = db
        indexes = (
            (('brand', 'customer'), True),
        )


class PriceChange(Model):
    product = ForeignKeyField(Product, backref='prices', on_update='CASCADE', on_delete='CASCADE')
    webshop = CharField()
    price = CharField()
    updated_at = DateTimeField(default=datetime.datetime.now)

    class Meta:
        database = db


class SmsQueue(Model):
    recipient = CharField()
    message = TextField()
    is_sent = BooleanField(default=False)
    sent_at = DateTimeField(null=True)
    queued_at = DateTimeField()

    @staticmethod
    def queue(message, recipient):
        '''Queue an SMS notification
        '''
        log("SMS queued for: " + recipient)
        return SmsQueue.create(message=message, recipient=recipient, queued_at=datetime.datetime.now())

    def send(self):
        '''Sends a message using twilio
        '''
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        log("SMS to: {}, id:  {}".format(self.recipient, self.id))
        try:
            message = client.messages.create(
                body=self.message,
                from_=TWILIO_FROM_NUMBER,
                to=self.recipient
            )
            log("SMS sid result: " + message.sid)
        except Exception as err:
            log("SMS Error:" + str(err))

    def sent(self):
        self.is_sent = True
        self.sent_at = datetime.datetime.now()
        self.save()

    class Meta:
        database = db

    class Form(FlaskForm):
        number_validators = [wtfv.DataRequired(), wtfv.Regexp(r'^\+(\d{7,})', message='Invalid mobile number. +XXXXXXXXXXX required')]

        recipient = wtf.StringField(validators=number_validators, widget=wtfw5.TelInput())
        message = wtf.TextAreaField(validators=[wtfv.DataRequired(), wtfv.Length(max=1600)])


class DebijenkorfScrapper(object):
    name = 'debijenkorf'
    BASE_URL = 'https://www.debijenkorf.nl/'
    SELECTOR = 'li.dbk-productlist--item'
    URL_SELECTOR = 'a.t-none'
    NAME_SELECTOR = '.dbk-product-info h2'
    IMAGE_SELECTOR = 'img'
    PRICE_SELECTOR = '.dbk-price.dbk-price_primary'
    DISCOUNT_SELECTOR = '.dbk-price.dbk-price_new'
    DISCOUNT_PERCENT_SELECTOR = '.signing--error'
    DESCRIPTION_SELECTOR = '.dbk-product-info p'
    LOAD_MORE_BUTTON_SELECTOR = 'a.loadmore-button'

    def __init__(self):
        self.brand = None
        self.page_soup = None
        self.pagination = None

    def product(self, soup):
        '''Creates a product object from soup
        '''
        try:
            price = soup.select_one(self.DISCOUNT_SELECTOR).get_text()
        except AttributeError:
            try:
                price = soup.select_one(self.PRICE_SELECTOR).get_text()
            except AttributeError:
                price = ''

        try:
            discount = soup.select_one(self.DISCOUNT_PERCENT_SELECTOR).get_text()
        except AttributeError:
                discount = ''

        return Product(
            url=soup.select_one(self.URL_SELECTOR)['href'],
            name=soup.select_one(self.NAME_SELECTOR).get_text(),
            image=soup.select_one(self.IMAGE_SELECTOR)['src'],
            description=soup.select_one(self.DESCRIPTION_SELECTOR).get_text(),
            price=price,
            brand_id=self.brand,
            discount=discount,
        )

    def url(self):
        return urllib.parse.urljoin(
            urllib.parse.urljoin(self.BASE_URL, self.brand),
            self.pagination
        )

    def soup(self, brand):
        ''':return: The soup for a specific brand
        '''
        log('Seeking from webshop: ' + self.name)
        products_soup = []
        self.brand = brand
        while self.has_more_pages():
            log('Fetching: ' + self.url())
            content = requests.get(self.url(), timeout=5).content
            self.page_soup = BeautifulSoup(content, 'html.parser')
            this_products_soup = self.page_soup.select(self.SELECTOR)
            self.replace_images(this_products_soup)
            products_soup.extend(this_products_soup)
        return products_soup

    def has_more_pages(self):
        if self.pagination is None:
            self.pagination = ''
            return True
        # Check for pagination and fetch again
        load_more_button = self.page_soup.select(self.LOAD_MORE_BUTTON_SELECTOR)
        if load_more_button and load_more_button[-1]['data-at'] == 'loadmore-next':
            self.pagination = load_more_button[-1]['href']
            return True
        return False

    def replace_images(self, products_soup):
        try:
            json_element = self.page_soup.select_one('[data-dbk-state="facetNavigation"]')
            context = json.loads(json_element.get_text())
            products = context['facetNavigation']['data']['products']
            images = {}
            for product in products:
                try:
                    code = product['defaultVariantCode']
                    url = product['currentVariantProduct']['images'][0]['url']
                    images[code] = url
                except Exception as e:
                    log(e)
            for product_soup in products_soup:
                code = product_soup.select_one('div > a')['name'][8:]
                product_soup.select_one(self.IMAGE_SELECTOR)['src'] = images[code]
        except Exception as e:
            log(e)


class CliApp(object):
    '''Main running space and functionality for command line application
    '''
    products = None
    scrappers = [DebijenkorfScrapper]

    def __init__(self):
        '''Initialize the application.
        '''
        self.products = {}
        for product in Product.select():
            self.products[product.id] = product

    def refresh_for(self, brand):
        '''Refresh the products for brand from each webshop
        '''
        updated_products = []
        log('Refreshing products for: ' + brand)
        for scrapper_cls in self.scrappers:
            scrapper = scrapper_cls()
            products_soup = scrapper.soup(brand)
            log('Updated products for: ' + brand)
            log('='*50)
            with db.atomic():
                for product_soup in products_soup:
                    product = scrapper.product(product_soup)
                    if product.id in self.products:
                        old_product = self.products[product.id]
                        has_price_update = product._price_not_eq(old_product.price, product.price)
                        if has_price_update:
                            log('PC: {1} ->{0.price} ({0.discount}%)'.format(product, product.id))
                            updated_products.append(product)
                            old_product.merge(product, scrapper.name)
                    else:
                        log('NP: {1} ->{0.price} ({0.discount}%)'.format(product, product.id))
                        product.save(force_insert=True)
                        self.products[product.id] = product
        log('='*50)
        log('')
        return updated_products

    def notify_for(self, updated_brands):
        '''Sends notifications for this brand.
        '''
        customer_to_brands = {}
        for brand, updated_brand in updated_brands.items():
            for customer in updated_brand['customers']:
                if customer not in customer_to_brands:
                    customer_to_brands[customer] = []
                if len(updated_brand['products']) > 0:
                    customer_to_brands[customer].append(brand)
        with db.atomic():
            for customer, brands in customer_to_brands.items():
                if len(brands) > 0:
                    SmsQueue.queue(customer.update_message(brands), customer.number)


class WebApp(object):
    '''Main running space for the web facing application
    '''

    def __init__(self, app):
        self.app = app
        self.setup_app()
        self.load_routes()

    def setup_app(self):
        self.app.secret_key = '97iybh2fuBYUgti7QG0-90876T0*(&*^%'
        self.app.before_request(self.before_request)
        self.app.teardown_request(self.teardown_request)

    def before_request(self):
        db.connect()

    def teardown_request(self, exc):
        if not db.is_closed():
            db.close()

    def load_routes(self):
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/profile', 'profile', self.profile)
        self.app.add_url_rule('/help', 'help', self.help)
        self.app.add_url_rule('/login', 'login', self.login, methods=['GET', 'POST'])
        self.app.add_url_rule('/logout', 'logout', self.logout)
        self.app.add_url_rule('/brand', 'brand_list', self.brand_list)
        self.app.add_url_rule('/brand/add', 'brand_form', self.brand_form, methods=['GET', 'POST'])
        self.app.add_url_rule('/brand/<name>/edit', 'brand_form', self.brand_form, methods=['GET', 'POST'])
        self.app.add_url_rule('/brand/<name>/remove', 'brand_remove', self.brand_remove, methods=['GET', 'POST'])
        self.app.add_url_rule('/customer', 'customer_list', self.customer_list)
        self.app.add_url_rule('/customer/add', 'customer_form', self.customer_form, methods=['GET', 'POST'])
        self.app.add_url_rule('/customer/<number>/subscription/', 'customer_subscription', self.customer_subscription)
        self.app.add_url_rule('/customer/<number>/<brand>/subscribe/', 'customer_subscribe', self.customer_subscribe, methods=['POST'])
        self.app.add_url_rule('/customer/<number>/edit', 'customer_form', self.customer_form, methods=['GET', 'POST'])
        self.app.add_url_rule('/customer/<number>/remove', 'customer_remove', self.customer_remove, methods=['GET', 'POST'])
        self.app.add_url_rule('/product', 'product_list', self.product_list)
        self.app.add_url_rule('/product/price', 'product_price', self.product_price)
        self.app.add_url_rule('/product/price/<id>', 'product_price', self.product_price)
        self.app.add_url_rule('/product/<id>/remove', 'product_remove', self.product_remove, methods=['GET', 'POST'])
        self.app.add_url_rule('/subscription', 'subscription_list', self.subscription_list)
        self.app.add_url_rule('/subscription/<name>', 'subscription_list', self.subscription_list)
        self.app.add_url_rule('/subscription/<id>/toggle', 'subscription_toggle', self.subscription_toggle, methods=['GET', 'POST'])
        self.app.add_url_rule('/subscription/<id>/<from_view>/toggle', 'subscription_toggle', self.subscription_toggle, methods=['GET', 'POST'])
        self.app.add_url_rule('/subscription/<id>/welcome', 'subscription_welcome', self.subscription_welcome, methods=['GET', 'POST'])
        self.app.add_url_rule('/subscription/<id>/<from_view>/welcome', 'subscription_welcome', self.subscription_welcome, methods=['GET', 'POST'])
        self.app.add_url_rule('/sms', 'sms_list', self.sms_list)
        self.app.add_url_rule('/sms/add', 'sms_add', self.sms_add, methods=['GET', 'POST'])
        self.app.add_url_rule('/<number>', 'customer_update', self.customer_update)

    @login_required
    def index(self):
        if request.customer.is_admin:
            return redirect(url_for('customer_list'))
        else:
            return redirect(url_for('customer_update', number=request.customer.number))

    @admin_required
    def brand_list(self):
        brands = Brand.select(Brand, fn.Count(Product.id).alias('num_products')) \
                    .join(Product, JOIN.LEFT_OUTER) \
                    .group_by(Brand).order_by(Brand.name)

        return render_template('brand_list.html', brands=brands)

    @admin_required
    def brand_form(self, name=None):
        try:
            brand = Brand.get(Brand.name==name) if name else Brand()
        except Brand.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            form = Brand.Form(request.form, obj=brand)
            if form.validate():
                if name is None:
                    form.populate_obj(brand)
                    brand.save(force_insert=True)
                else:
                    Brand.update(name=form.data['name']).where(Brand.name==name).execute()
                flash('Successfully saved brand')
                return redirect(url_for('brand_list'))
        else:
            form = Brand.Form(obj=brand)
        return render_template('brand_form.html', brand=brand, form=form)

    @admin_required
    def brand_remove(self, name):
        try:
            brand = Brand.get(Brand.name==name)
        except Brand.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            brand.delete_instance(True)
            flash('Successfully deleted ' + name)
            return redirect(url_for('brand_list'))
        return render_template('brand_remove.html', brand=brand)

    @admin_required
    def customer_list(self):
        customers = Customer.select(Customer, Subscription).join(Subscription, JOIN.LEFT_OUTER).group_by(Customer).order_by(Customer.number)
        return render_template('customer_list.html', customers=customers)

    @admin_required
    def customer_form(self, number=None):
        try:
            customer = Customer.get(Customer.number==number) if number else Customer()
        except Customer.DoesNotExist:
            abort(404)
        customer.id = number
        if request.method == 'POST':
            form = Customer.Form(request.form, obj=customer)
            if form.validate():
                if number is None:
                    form.populate_obj(customer)
                    customer.save(force_insert=True)
                else:
                    data = form.data
                    del data['id']
                    del data['csrf_token']
                    data['password'] = data['password'] if data['password'] else customer.gen_password()
                    Customer.update(**data).where(Customer.number==number).execute()
                flash('Successfully saved customer')
                return redirect(url_for('customer_list'))
        else:
            form = Customer.Form(obj=customer)
        return render_template('customer_form.html', customer=customer, form=form)

    @admin_required
    def customer_subscription(self, number):
        try:
            customer = Customer.get(Customer.number==number)
        except Customer.DoesNotExist:
            abort(404)
        brands = Brand.select().order_by(Brand.name)
        subscriptions = {s.brand_id: s for s in Subscription.select()
                                .where(Subscription.customer_id==number)
                                .order_by(Subscription.brand_id)}
        for brand in brands:
            if brand.name in subscriptions:
                subscription = subscriptions[brand.name]
                brand.subscription_id = subscription.id
                brand.is_subscribed = subscription.is_subscribed
                brand.has_welcome = subscription.has_welcome

        return render_template('customer_subscription.html', brands=brands, customer=customer)

    @admin_required
    def customer_subscribe(self, number, brand):
        try:
            subscription = Subscription.select().where(Subscription.customer_id==number).where(Subscription.brand_id==brand).get()
        except Subscription.DoesNotExist:
            subscription = Subscription(customer_id=number, brand_id=brand, is_subscribed=False)
        if not subscription.is_subscribed:
            subscription.subscribe()
            flash('Successfully subscribed')
        else:
            subscription.unsubscribe()
            flash('Successfully unsubscribed')
        return redirect(url_for('customer_subscription', number=number))

    @login_required
    def customer_update(self, number):
        subscribed_brands = Subscription.select(Subscription.brand_id).where(Subscription.customer_id==number)
        prices = (PriceChange.select(PriceChange, Product)
                        .join(Product)
                        .where(PriceChange.product.brand.in_(subscribed_brands))
                        .order_by(-PriceChange.updated_at)
                        .group_by(PriceChange.product_id)
                        .having(fn.max(PriceChange.updated_at))
        )
        return render_template('customer_update.html', prices=prices)

    @admin_required
    def customer_remove(self, number):
        try:
            customer = Customer.get(Customer.number==number)
        except Customer.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            customer.delete_instance(True)
            flash('Successfully deleted ' + number)
            return redirect(url_for('customer_list'))
        return render_template('customer_remove.html', customer=customer)

    @admin_required
    def product_list(self):
        return render_template('product_list.html', products=Product.select().order_by(Product.name))

    @admin_required
    def product_price(self, id=None):
        prices = PriceChange.select(PriceChange, Product).join(Product).order_by(-PriceChange.updated_at)
        if id:
            prices = prices.where(PriceChange.product.id==id)
        return render_template('product_price.html', prices=prices)

    @admin_required
    def product_remove(self, id):
        try:
            product = Product.get(Product.id==id)
        except Product.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            product.delete_instance(True)
            flash('Successfully deleted ' + id)
            return redirect(url_for('product_list'))
        return render_template('product_remove.html', product=product)

    @admin_required
    def subscription_list(self, name=None):
        subscriptions = Subscription.select().order_by(Subscription.brand_id)
        if name:
            subscriptions = subscriptions.where(Subscription.brand_id==name)
        return render_template('subscription_list.html', subscriptions=subscriptions)

    @admin_required
    def subscription_toggle(self, id, from_view='customer_subscription'):
        try:
            subscription = Subscription.get(Subscription.id==id)
        except Subscription.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            if subscription.is_subscribed:
                flash('Successfully unsubscribed ' + subscription.customer_id)
                subscription.unsubscribe()
            else:
                flash('Successfully subscribed ' + subscription.customer_id)
                subscription.subscribe()
            return redirect(url_for(from_view, number=subscription.customer_id))
        return render_template('subscription_toggle.html', subscription=subscription)

    @admin_required
    def subscription_welcome(self, id, from_view='customer_subscription'):
        try:
            subscription = Subscription.get(Subscription.id==id)
        except Subscription.DoesNotExist:
            abort(404)
        if request.method == 'POST':
            subscription.welcome()
            return redirect(url_for(from_view, number=subscription.customer_id))
        return render_template('subscription_welcome.html', subscription=subscription)

    @admin_required
    def sms_list(self):
        return render_template('sms_list.html', smses=SmsQueue.select().order_by(-SmsQueue.queued_at))

    @admin_required
    def sms_add(self):
        if request.method == 'POST':
            form = SmsQueue.Form(request.form)
            if form.validate():
                SmsQueue.queue(form.data['message'], form.data['recipient'])
                flash('Successfully queued message for sending')
                return redirect(url_for('sms_list'))
        else:
            form = SmsQueue.Form()
        return render_template('sms_add.html', form=form)

    @login_required
    def profile(self):
        return render_template('profile.html')

    @login_required
    def help(self):
        return render_template('help.html')

    def login(self):
        if 'customer' in session:
            try:
                customer = Customer.get(Customer.number==session['customer'])
                return redirect(url_for('index'))
            except Customer.DoesNotExist:
                pass
        if request.method == 'POST':
            form = Customer.LoginForm(request.form)
            if form.validate():
                session['customer'] = form.data['number']
                next_url = request.args.get('next_url', None)
                next_url = next_url if next_url and (next_url not in (url_for('login'), url_for('logout'))) else url_for('index')
                return redirect(next_url)
        else:
            form = Customer.LoginForm()
        return render_template('login.html', form=form)

    def logout(self):
        session.pop('customer', None)
        return redirect(url_for('login'))


def sms_messenger():
    while True:
        try:
            unsent_messages = SmsQueue.select().where(SmsQueue.is_sent==False)
            with db.atomic():
                for message in unsent_messages:
                    message.send()
                    message.sent()
            time.sleep(SMS_TIMEOUT)
        except KeyboardInterrupt:
            break


def scrapper():
    app = CliApp()
    while True:
        try:
            updated_brands = {}
            for brand, customers in Subscription.brands().items():
                updated_brands[brand] = {
                    'products': app.refresh_for(brand),
                    'customers': customers,
                }
            app.notify_for(updated_brands)
            time.sleep(WAIT_TIMEOUT)
        except KeyboardInterrupt:
            break


def server():
    app = Flask(__name__)
    web_app = WebApp(app)
    app.run(debug=True)


if __name__ == '__main__':
    if "--server" in sys.argv:
        server()
    elif "--sms-messenger" in sys.argv:
        sms_messenger()
    else:
        scrapper()
