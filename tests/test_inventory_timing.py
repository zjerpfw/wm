import importlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class InventoryTimingIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = importlib.import_module('backend.app.main')
        cls.app.AppHandler.log_message = lambda *args: None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'wm_test.db'
        self.app.DB_PATH = self.db_path
        self.app.init_db()
        self.server = self.app.ThreadingHTTPServer(('127.0.0.1', 0), self.app.AppHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f'http://{host}:{port}'
        self.seed_master_data()
        self.purchase_stock(quantity=10)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def request(self, path, method='GET', body=None, expected_status=200):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(f'{self.base_url}{path}', data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = json.loads(exc.read().decode('utf-8'))
        self.assertEqual(status, expected_status, payload)
        return payload

    def seed_master_data(self):
        self.request('/api/products', 'POST', {'product_code': 'P1', 'name': 'Prod1'})
        self.request('/api/customers', 'POST', {'code': 'C1', 'name': 'Cust1'})
        self.request('/api/suppliers', 'POST', {'code': 'S1', 'name': 'Supp1'})

    def purchase_stock(self, quantity):
        self.request(
            '/api/purchases',
            'POST',
            {
                'purchase_no': 'PO1',
                'supplier_id': 1,
                'status': 'SAVED',
                'items': [{'product_id': 1, 'quantity': quantity, 'unit_price': 2}],
            },
        )

    def create_sales_order(self, sales_no='SO1', quantity=6):
        payload = self.request(
            '/api/orders',
            'POST',
            {
                'sales_no': sales_no,
                'customer_id': 1,
                'status': 'SAVED',
                'items': [{'product_id': 1, 'quantity': quantity, 'unit_price': 5}],
            },
        )
        return int(payload['data']['id'])

    def create_shipment(self, sales_order_id, shipment_no='SH1'):
        payload = self.request(
            '/api/shipments',
            'POST',
            {'sales_order_id': sales_order_id, 'shipment_no': shipment_no},
        )
        return int(payload['data']['id'])

    def inventory_summary(self):
        payload = self.request('/api/inventory/summary')
        return payload['data'][0]

    def inventory_on_hand(self):
        return float(self.inventory_summary()['on_hand'])

    def shipment_item_id(self, shipment_id):
        payload = self.request(f'/api/shipments/{shipment_id}')
        return int(payload['data']['items'][0]['id'])

    def movement_by_ref_type(self, ref_type):
        payload = self.request('/api/inventory/movements')
        return [row for row in payload['data'] if row['ref_type'] == ref_type]

    def test_inventory_moves_only_on_shipment_status_transitions(self):
        self.assertEqual(self.inventory_on_hand(), 10.0)

        order_id = self.create_sales_order('SO-FLOW', 6)
        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(f'/api/orders/{order_id}', 'PUT', {'status': 'SAVED', 'note': 'update-without-items'})
        self.assertEqual(self.inventory_on_hand(), 10.0)

        shipment_id = self.create_shipment(order_id, 'SH-FLOW')
        self.assertEqual(self.inventory_on_hand(), 10.0)

        save_payload = self.request(
            f'/api/shipments/{shipment_id}',
            'PUT',
            {'shipment_no': 'SH-FLOW', 'status': 'SAVED'},
        )
        self.assertIn('扣库存', save_payload['data']['message'])
        self.assertEqual(self.inventory_on_hand(), 4.0)

        self.request(
            f'/api/shipments/{shipment_id}',
            'PUT',
            {'shipment_no': 'SH-FLOW', 'status': 'SAVED'},
        )
        self.assertEqual(self.inventory_on_hand(), 4.0)

        shipment_rows = self.movement_by_ref_type('SHIPMENT')
        self.assertEqual(len(shipment_rows), 1)
        self.assertEqual(shipment_rows[0]['ref_id'], shipment_id)
        self.assertEqual(shipment_rows[0]['ref_no'], 'SH-FLOW')

        void_payload = self.request(
            f'/api/shipments/{shipment_id}',
            'PUT',
            {'shipment_no': 'SH-FLOW', 'status': 'VOIDED'},
        )
        self.assertIn('回补', void_payload['data']['message'])
        self.assertEqual(self.inventory_on_hand(), 10.0)

        repeat_void = self.request(
            f'/api/shipments/{shipment_id}',
            'PUT',
            {'shipment_no': 'SH-FLOW', 'status': 'VOIDED'},
            expected_status=400,
        )
        self.assertIn('已作废发货单不允许修改', repeat_void['error'])
        self.assertEqual(self.inventory_on_hand(), 10.0)

        void_rows = self.movement_by_ref_type('VOID_SHIPMENT')
        self.assertEqual(len(void_rows), 1)
        self.assertEqual(void_rows[0]['ref_id'], shipment_id)
        self.assertEqual(void_rows[0]['ref_no'], 'SH-FLOW')

    def test_boxing_create_update_delete_does_not_change_inventory(self):
        order_id = self.create_sales_order('SO-BOX', 6)
        shipment_id = self.create_shipment(order_id, 'SH-BOX')
        shipment_item_id = self.shipment_item_id(shipment_id)

        self.assertEqual(self.inventory_on_hand(), 10.0)

        box_payload = self.request(
            f'/api/shipments/{shipment_id}/boxes',
            'POST',
            {'box_no': '1', 'gross_weight': 1.5},
        )
        box_id = int(box_payload['data']['id'])
        self.assertEqual(self.inventory_on_hand(), 10.0)

        item_payload = self.request(
            f'/api/shipments/{shipment_id}/boxes/{box_id}/items',
            'POST',
            {'shipment_item_id': shipment_item_id, 'qty': 2},
        )
        box_item_id = int(item_payload['data']['id'])
        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(
            f'/api/shipments/{shipment_id}/boxes/{box_id}/items/{box_item_id}',
            'PUT',
            {'shipment_item_id': shipment_item_id, 'qty': 3, 'remark': 'updated'},
        )
        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(
            f'/api/shipments/{shipment_id}/boxes/{box_id}',
            'PUT',
            {'box_no': '1', 'gross_weight': 2.0, 'net_weight': 1.0, 'volume': 0.3},
        )
        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(f'/api/shipments/{shipment_id}/boxes/{box_id}/items/{box_item_id}', 'DELETE')
        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(f'/api/shipments/{shipment_id}/boxes/{box_id}', 'DELETE')
        self.assertEqual(self.inventory_on_hand(), 10.0)

    def test_draft_to_voided_does_not_reverse_nonexistent_inventory(self):
        order_id = self.create_sales_order('SO-DRAFT-VOID', 6)
        shipment_id = self.create_shipment(order_id, 'SH-DRAFT-VOID')

        self.assertEqual(self.inventory_on_hand(), 10.0)

        self.request(
            f'/api/shipments/{shipment_id}',
            'PUT',
            {'shipment_no': 'SH-DRAFT-VOID', 'status': 'VOIDED'},
        )
        self.assertEqual(self.inventory_on_hand(), 10.0)
        self.assertEqual(self.movement_by_ref_type('VOID_SHIPMENT'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
