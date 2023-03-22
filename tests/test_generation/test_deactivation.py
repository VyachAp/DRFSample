import datetime
import uuid
import json
import pytest
from src.goal.models.card import Card
from src.goal import tasks
from src.goal.tasks.cards_generation import _generate_cards_for_unit
from tests.factories.card import CardNoSignalFactory, EmployeeBonusTypeFactory
from tests.factories.period import PeriodTypeFactory, PeriodFactory


@pytest.fixture
def mock_get_employees_by_orgstructure(mocker):
    def _get_employees_by_orgstructure(json_file):
        with open(json_file, "r") as f:
            response = json.load(f)
        return mocker.patch("src.goal.tasks.cards_generation.get_employees_by_orgstructure", return_value=response)
    return _get_employees_by_orgstructure


@pytest.mark.django_db
class TestDeactivation:

    @pytest.fixture
    def create_period_settings(self, django_db_setup):
        self.period_type = PeriodTypeFactory.create(name="Год")
        self.bonus_type_ga = EmployeeBonusTypeFactory.create(key="9GA1")
        self.bonus_type_gf = EmployeeBonusTypeFactory.create(key="9GF1")

        self.period = PeriodFactory.create(
            year=2022,
            period="2022 (II)",
            is_active=True,
            date_start=datetime.date(year=2022, month=7, day=1),
            date_end=datetime.date(year=2022, month=12, day=31),
            cards_generation_end_date=datetime.date(year=2022, month=10, day=1),
            cards_assessment_end_date=datetime.date(year=2023, month=2, day=28),
            cards_bonus_payout_date=datetime.date(year=2023, month=3, day=10),
            worked_days_number=90,
            period_type=self.period_type,
        )
        self.period.bonus_types.set([self.bonus_type_ga, self.bonus_type_gf])

    def test_2047458(self, create_period_settings, mock_get_employees_by_orgstructure):
        """Удаление второстепенных атрибутов у уволенного сотрудника (дублирование записи об увольнении спустя время)"""
        bus_unit_id = "53822103"
        card = CardNoSignalFactory.create(
            perno="2047458",
            business_unit=bus_unit_id,
            status=Card.APPROVED.key,
            state=Card.ACTIVE.key,
            stage=Card.ON_SETTING.key,
            period=self.period,
            date_start=datetime.date(year=2022, month=12, day=16),
            date_end=datetime.date(year=2022, month=12, day=31),
            dt_created=datetime.date(year=2022, month=10, day=3),
            bonus_type=self.bonus_type_ga,
        )
        mock_get_employees_by_orgstructure('tests/test_generation/fixtures/mock_2047458.json')
        data = _generate_cards_for_unit(bus_unit_id, self.period.id, uuid.uuid4())
        assert data
        assert data["checked"] == 1
        assert data["deactivated"] == 0
        existing_card = Card.objects.get(pk=card.id)
        assert existing_card.state == Card.ACTIVE.key

    def test_2047445(self, create_period_settings, mock_get_employees_by_orgstructure):
        bus_unit_id = "53822085"
        card = CardNoSignalFactory.create(
            perno="2047445",
            business_unit=bus_unit_id,
            status=Card.APPROVED.key,
            state=Card.ACTIVE.key,
            stage=Card.ON_SETTING.key,
            period=self.period,
            date_start=datetime.date(year=2022, month=12, day=16),
            date_end=datetime.date(year=2022, month=12, day=31),
            dt_created=datetime.date(year=2022, month=10, day=3),
            bonus_type=self.bonus_type_ga,
        )
        mock_get_employees_by_orgstructure('tests/test_generation/fixtures/mock_2047445.json')
        data = _generate_cards_for_unit(bus_unit_id, self.period.id, uuid.uuid4())
        assert data
        assert data["checked"] == 1
        assert data["deactivated"] == 0
        existing_card = Card.objects.get(pk=card.id)
        assert existing_card.state == Card.ACTIVE.key

    def test_2022514(self, create_period_settings, mock_get_employees_by_orgstructure):
        bus_unit_id = "53798603"
        card = CardNoSignalFactory.create(
            perno="2022514",
            business_unit=bus_unit_id,
            status=Card.APPROVED.key,
            state=Card.ACTIVE.key,
            stage=Card.ON_SETTING.key,
            period=self.period,
            date_start=datetime.date(year=2022, month=11, day=1),
            date_end=datetime.date(year=2022, month=11, day=30),
            dt_created=datetime.date(year=2022, month=10, day=3),
            bonus_type=self.bonus_type_ga,
        )
        mock_get_employees_by_orgstructure('tests/test_generation/fixtures/mock_2022514.json')
        data = _generate_cards_for_unit(bus_unit_id, self.period.id, uuid.uuid4())
        assert data
        assert data["checked"] == 1
        assert data["deactivated"] == 0
        existing_card = Card.objects.get(pk=card.id)
        assert existing_card.state == Card.ACTIVE.key

    def test_1940557(self, create_period_settings, mock_get_employees_by_orgstructure):
        bus_unit_id = "53792441"
        card = CardNoSignalFactory.create(
            perno="1940557",
            business_unit=bus_unit_id,
            status=Card.APPROVED.key,
            state=Card.ACTIVE.key,
            stage=Card.ON_SETTING.key,
            period=self.period,
            date_start=datetime.date(year=2022, month=7, day=1),
            date_end=datetime.date(year=2022, month=12, day=31),
            dt_created=datetime.date(year=2022, month=10, day=3),
            bonus_type=self.bonus_type_ga,
        )
        mock_get_employees_by_orgstructure('tests/test_generation/fixtures/mock_1940557.json')
        data = _generate_cards_for_unit(bus_unit_id, self.period.id, uuid.uuid4())
        assert data
        assert data["checked"] == 1
        assert data["deactivated"] == 0
        existing_card = Card.objects.get(pk=card.id)
        assert existing_card.state == Card.ACTIVE.key
