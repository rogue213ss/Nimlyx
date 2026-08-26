import unittest
from app import app
from steam import _CURRENCY_SYMBOLS, _format_price_cents

class TestGameDetailRegression(unittest.TestCase):
    def test_currency_symbols_defined(self):
        # Regression test to ensure _CURRENCY_SYMBOLS is defined and format_price_cents works.
        self.assertIn('USD', _CURRENCY_SYMBOLS)
        self.assertEqual(_CURRENCY_SYMBOLS['USD'], '$')
        
        # Test valid formatting
        self.assertEqual(_format_price_cents(1499, 'USD'), '$14.99')
        self.assertEqual(_format_price_cents(1000, 'UNKNOWN'), 'UNKNOWN 10.00')

    def test_game_detail_endpoint_success(self):
        # Regression test to ensure the game detail endpoint doesn't 500 on valid apps with prices/packages.
        app.testing = True
        with app.test_client() as client:
            # CS:GO (App ID 730) has packages with prices, triggering build_purchase_options
            resp = client.get('/api/game-detail/730')
            self.assertEqual(resp.status_code, 200)
            data = resp.json
            self.assertIsNotNone(data)
            self.assertEqual(data['app_id'], '730')

if __name__ == '__main__':
    unittest.main()
