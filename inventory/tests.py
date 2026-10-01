from datetime import date
from decimal import Decimal
import json

from auditlog.context import auditlog_disabled
from django.test import RequestFactory, TestCase

from core.models import Modality
from orders.models import ExamOrder
from patients.models import Patient
from users.models import User

from .models import Category, InventoryItem, StockTransaction
from .services import (
    InsufficientStockError,
    InventoryError,
    add_stock,
    adjust_stock,
    consume_exam_materials,
    record_stock_movement,
)
from .views import inventory_dashboard, inventory_list


class InventoryServiceTests(TestCase):
    def setUp(self):
        self.auditlog_token = auditlog_disabled.set(True)
        self.user = User.objects.create_user(
            username="tech",
            email="tech@example.test",
            password="test-password",
        )
        self.category = Category.objects.create(name="Contrast Media")
        self.item = InventoryItem.objects.create(
            name="Iodinated contrast",
            sku="CONTRAST-001",
            category=self.category,
            unit_of_measure="Vial",
            current_stock_level=Decimal("2.000"),
            low_stock_threshold=Decimal("1.000"),
        )
        patient = Patient.objects.create(
            mrn="MRN-001",
            first_name_en="Test",
            last_name_en="Patient",
            dob=date(1980, 1, 1),
            gender="O",
        )
        modality = Modality.objects.create(code="CT", name="Computed Tomography")
        self.exam = ExamOrder.objects.create(
            patient=patient,
            modality=modality,
            accession_number="ACC-001",
            procedure_code="CT_ABD_C",
            procedure_name_en="CT abdomen with contrast",
        )

    def tearDown(self):
        auditlog_disabled.reset(self.auditlog_token)

    def test_add_stock_updates_level_and_creates_in_transaction(self):
        entry = add_stock(self.item.pk, "1.500", self.user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("3.500"))
        self.assertEqual(entry.transaction_type, StockTransaction.TransactionType.IN)
        self.assertEqual(entry.quantity, Decimal("1.500"))

    def test_adjustment_records_signed_delta(self):
        entry = adjust_stock(self.item.pk, "-0.500", self.user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("1.500"))
        self.assertEqual(
            entry.transaction_type,
            StockTransaction.TransactionType.ADJUSTMENT,
        )
        self.assertEqual(entry.quantity, Decimal("-0.500"))

    def test_record_stock_movement_supports_in_out_and_optional_exam(self):
        stock_in = record_stock_movement(
            self.item.pk,
            StockTransaction.TransactionType.IN,
            "1.000",
            self.user,
        )
        stock_out = record_stock_movement(
            self.item.pk,
            StockTransaction.TransactionType.OUT,
            "0.500",
            self.user,
            exam=self.exam,
        )

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("2.500"))
        self.assertEqual(stock_in.transaction_type, StockTransaction.TransactionType.IN)
        self.assertIsNone(stock_in.exam)
        self.assertEqual(stock_out.transaction_type, StockTransaction.TransactionType.OUT)
        self.assertEqual(stock_out.exam, self.exam)

    def test_inventory_dashboard_renders_category_and_low_stock_state(self):
        self.item.current_stock_level = Decimal("0.500")
        self.item.save(update_fields=["current_stock_level"])
        request = RequestFactory().get("/inventory/")
        request.user = self.user
        response = inventory_dashboard(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Radiology Inventory", response.content)
        self.assertIn(b"Low stock", response.content)
        self.assertIn(b"Contrast Media", response.content)

    def test_order_detail_includes_exam_consumption_widget(self):
        from orders.views import order_detail

        request = RequestFactory().get(f"/orders/{self.exam.pk}/")
        request.user = self.user
        response = order_detail(request, self.exam.pk)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"exam-inventory-consumption", response.content)
        self.assertIn(b"consume-exam/", response.content)

    def test_exam_consumption_updates_stock_and_flags_low_stock(self):
        result = consume_exam_materials(
            self.exam.pk,
            [
                {"item_id": str(self.item.pk), "quantity": "0.250"},
                {"item_id": str(self.item.pk), "quantity": "0.250"},
            ],
            self.user,
        )

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("1.500"))
        self.assertEqual(result["transactions"][0].transaction_type, "OUT")
        self.assertEqual(result["transactions"][0].exam, self.exam)
        self.assertEqual(result["low_stock_items"], [])

        result = consume_exam_materials(
            self.exam.pk,
            [{"item_id": str(self.item.pk), "quantity": "0.500"}],
            self.user,
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("1.000"))
        self.assertEqual([item.pk for item in result["low_stock_items"]], [self.item.pk])

    def test_exam_consumption_rolls_back_entire_batch_if_stock_is_insufficient(self):
        low_item = InventoryItem.objects.create(
            name="Syringe",
            sku="SYRINGE-001",
            category=self.category,
            unit_of_measure="Each",
            current_stock_level=Decimal("0.250"),
            low_stock_threshold=Decimal("0.100"),
        )

        with self.assertRaises(InsufficientStockError):
            consume_exam_materials(
                self.exam.pk,
                [
                    {"item_id": str(self.item.pk), "quantity": "1.000"},
                    {"item_id": str(low_item.pk), "quantity": "0.500"},
                ],
                self.user,
            )

        self.item.refresh_from_db()
        low_item.refresh_from_db()
        self.assertEqual(self.item.current_stock_level, Decimal("2.000"))
        self.assertEqual(low_item.current_stock_level, Decimal("0.250"))
        self.assertFalse(StockTransaction.objects.exists())

    def test_consume_rejects_nonpositive_and_overprecision_quantities(self):
        for quantity in ("0", "-1", "0.0001"):
            with self.subTest(quantity=quantity), self.assertRaises(InventoryError):
                consume_exam_materials(
                    self.exam.pk,
                    [{"item_id": str(self.item.pk), "quantity": quantity}],
                    self.user,
                )

    def test_inventory_endpoint_can_filter_low_stock_items(self):
        self.item.current_stock_level = Decimal("0.500")
        self.item.save(update_fields=["current_stock_level"])
        request = RequestFactory().get("/inventory/items/?low_stock=true")
        request.user = self.user
        response = inventory_list(request)

        self.assertEqual(response.status_code, 200)
        items = json.loads(response.content)["items"]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["is_low_stock"])
