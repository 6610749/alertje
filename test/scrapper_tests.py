import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest import mock
from playhouse.db_url import connect


path = lambda *args: os.path.join(os.path.dirname(os.path.abspath(__file__)), *args)


class Runner:
    count = 0


def mocked_connect(url):
    db = path('file.db')
    try:
        os.unlink(db)
    except FileNotFoundError:
        pass
    return connect('sqlite:///{}'.format(db))


with mock.patch('playhouse.db_url.connect', side_effect=mocked_connect) as mc:
    import main
    import manage


class MockResponse(object):
    def __init__(self, content, status=200):
        self.content = content
        self.status = status


def mocked_request_get(url, timeout=0):
    filepath = None
    if url == "https://www.debijenkorf.nl/off-white":
        if Runner.count == 0:
            filepath = 'off-white-1.html'
        else:
            filepath = 'off-white-1-new.html'
    elif url == "https://www.debijenkorf.nl/off-white?page=2":
        filepath = 'off-white-2.html'
    elif url == "https://www.debijenkorf.nl/off-white?page=3":
        filepath = 'off-white-3.html'

    if filepath:
        with open(path(filepath)) as f:
            return MockResponse(f.read(), 200)
    return MockResponse('', 404)


def mocked_time_sleep(time):
    Runner.count += 1
    if Runner.count == 2:
        raise KeyboardInterrupt("Break out of loop!")


class TestScrapper(unittest.TestCase):

    def populateDatabase(self):
        manage.migrate()
        main.Brand.create(name='off-white')
        customer = main.Customer.create(number='+310000001')
        subscriber = main.Subscription.create(customer_id='+310000001', brand_id='off-white', is_subscribed=True)

    @mock.patch('main.VERBOSE', False)
    @mock.patch('requests.get', side_effect=mocked_request_get)
    @mock.patch('time.sleep', side_effect=mocked_time_sleep)
    def test_getting_products(self, mock_get, mock_sleep):
        self.populateDatabase()
        main.scrapper()

        # check updated images
        self.assertTrue(main.Product.select().count() == 108)
        for product in main.Product.select():
            self.assertFalse(product.image.startswith('data:image'))

        # check updated prices
        self.assertTrue(main.PriceChange.select().count() == 1)
        change = main.PriceChange.get(product_id='off-white-70s-vintage-t-shirt-met-logoprint-6649080002-664908000211001')
        self.assertTrue(float(change.price) == 192.5)

        self.assertTrue(main.SmsQueue.select().count() == 1)
        sms = main.SmsQueue.select()[0]
        self.assertTrue(sms.message == main.UPDATE_MESSAGE.format(brands='off-white', url='http://client.alertje.nl/+310000001'))


if __name__ == '__main__':
    unittest.main()