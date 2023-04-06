import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
from uuid import UUID

from django.apps import apps

from src.goal.models.card import Card
from src.goal.models.period import Period
from src.goal.services.card_generation.bonus import BonusHandler
from src.goal.services.card_generation.card_deactivate_manager import (
    EmployeeCardDeactivateManager,
    UnitCardDeactivateManager,
)
from src.goal.services.card_generation.consts import (
    CardActivity,
    ChangeReasonType,
    EmployeeStatus,
    OrganizationMethod,
)
from src.goal.services.card_generation.existing_card_manager import ExistingCardManager
from src.goal.services.card_generation.filter import FilterEmployee


logger = logging.getLogger(__name__)


class CardGenerationService:
    """Сервис для генерации карт в разрезе периода"""

    def __init__(self, period: Period, task_id: UUID):
        self.period = period
        self.task_id = task_id
        self.bonus_handler = BonusHandler(self.period)
        self.employee_deactivate_manager = EmployeeCardDeactivateManager(self.period)
        self.unit_deactivate_manager = UnitCardDeactivateManager(self.period)
        self.results = {s.value: 0 for s in CardActivity}
        self.employee_cards = defaultdict(set)
        self.employee_fired = {}

    @staticmethod
    def _dttm_from_str_to_date(str_dttm):
        return datetime.strptime(str_dttm, "%Y-%m-%dT%H:%M:%S%z").date()

    def _recalculate_hire_dt(self, historical_records: List[Dict]):
        # need to pass through all record actual hire_dt if employee turned back/re-hired in 2 weeks
        prev_record = None
        for record in historical_records:
            if (
                record["position"]["employee_group"]
                in (
                    OrganizationMethod.hourly.value,
                    OrganizationMethod.salary.value,
                )
                and record["position"]["employee_status"] == EmployeeStatus.active.value
            ):
                if (
                    prev_record
                    and (
                        self._dttm_from_str_to_date(record["business_from_dttm"])
                        - self._dttm_from_str_to_date(prev_record["business_to_dttm"])
                    ).days
                    < 14
                ):
                    record["hire_dt"] = prev_record["hire_dt"]
                prev_record = record

    def _intent_to_create_card(self, records: List[Dict]) -> None:
        Card = apps.get_model("goal.Card")
        EmployeeBonusType = apps.get_model("goal.EmployeeBonusType")
        card_start_dt = max(
            self.period.date_start,
            self._dttm_from_str_to_date(records[0]["business_from_dttm"]),
        )
        card_end_dt = min(
            self.period.date_end,
            self._dttm_from_str_to_date(records[-1]["business_to_dttm"]),
        )

        result_card_dates = self.bonus_handler.apply_bonus_dates(
            records, (card_start_dt, card_end_dt)
        )

        for dates in result_card_dates:
            if FilterEmployee(dates, records, self.period).is_suited():
                existing_card = Card.objects.filter(
                    perno=records[0]["per_no"],
                    period_id=self.period.id,
                    date_start=dates["start"],
                ).first()

                if existing_card and existing_card.generation_task_id != self.task_id:
                    # it means that other generation run already created card with such parameters
                    activity = ExistingCardManager(existing_card).handle_existing_card(
                        dates
                    )
                    self.results[activity] += 1
                    self.employee_cards[records[0]["per_no"]].add(existing_card.id)
                    continue

                elif existing_card and existing_card.generation_task_id == self.task_id:
                    self.employee_cards[records[0]["per_no"]].add(existing_card.id)
                    continue

                bonus_type = EmployeeBonusType.objects.get(key=dates["type"])
                card = Card.objects.create(
                    perno=records[0]["per_no"],
                    business_unit=dates["business_unit"],
                    bonus_type=bonus_type,
                    period_id=self.period.id,
                    date_start=dates["start"],
                    date_end=dates["end"],
                    generation_task_id=self.task_id,
                )

                self.results[CardActivity.created.value] += 1
                self.employee_cards[records[0]["per_no"]].add(card.id)

    @staticmethod
    def get_last_record(historical_records, per_no):
        for record in reversed(historical_records):
            if record["per_no"] == per_no:
                return record

    def get_last_fired_record(self, historical_records):
        return_index, return_record = -1, {}
        for index, record in enumerate(historical_records):
            if (
                record["position"]["employee_status"] == EmployeeStatus.fired.value
                and record["position"]["employee_group"]
                in (
                    OrganizationMethod.hourly.value,
                    OrganizationMethod.salary.value,
                )
                and datetime.fromisoformat(record["fire_dt"]).date()
                == (
                    self._dttm_from_str_to_date(record["business_from_dttm"])
                    - timedelta(days=1)
                )
            ):
                return_index = index
                return_record = record
        return return_index, return_record

    def generate_cards_for_employee(self, employee):
        """Генерация карт для сотрудника за период"""
        prev_record = {}
        records_to_perform_creation = []
        per_no = employee["per_no"]
        # Only main employee_group
        employee["historical_records"] = [
            it
            for it in employee["historical_records"]
            if it["position"]["employee_group"]
            in (
                OrganizationMethod.salary.value,
                OrganizationMethod.hourly.value,
            )
        ]
        # Check if employee generally has data about it's work leaving
        fire_data = self.employee_deactivate_manager.find_employee_quit_data(
            employee["historical_records"]
        )
        self.employee_fired[per_no] = fire_data if fire_data else None
        self._recalculate_hire_dt(employee["historical_records"])
        if (
            self.employee_fired[per_no]
            and self.get_last_record(employee["historical_records"], per_no)[
                "position"
            ]["employee_status"]
            == EmployeeStatus.fired.value
        ):
            # if employee was fired and the last record is only about it, so we need to only deactivate current cards
            self.employee_deactivate_manager.check_cards_for_deactivation(
                per_no, self.employee_fired[per_no]
            )
            return

        if self.employee_fired[
            per_no
        ]:  
            # if it was fired, but now works - let's check all the cards before fire
            fired_record_index, fired_record = self.get_last_fired_record(
                employee["historical_records"]
            )
            old_cards_ids = (
                Card.objects.filter(period=self.period, perno=per_no)
                .exclude(
                    date_end__gt=datetime.fromisoformat(fired_record["fire_dt"]),
                )
                .values_list("pk", flat=True)
            )
            self.employee_deactivate_manager.check_cards_for_deactivation(
                per_no, self.employee_fired[per_no], set(old_cards_ids)
            )
            # only fresh records now make interest
            employee["historical_records"] = employee["historical_records"][
                fired_record_index + 1 :
            ]
        for record in employee["historical_records"]:
            business_to_dttm = self._dttm_from_str_to_date(record["business_to_dttm"])
            if business_to_dttm < self.period.date_start or record["per_no"] != per_no:
                # Its' agreement that records are coming from old to new one
                continue
            if (
                self._dttm_from_str_to_date(record["business_from_dttm"])
                > self.period.date_end
            ):  
                break
            if not prev_record:
                prev_record = record
                records_to_perform_creation.append(record)
                continue
            if (
                prev_record["division"]["unit"]
                == record["division"][
                    "unit"
                ]  
                and prev_record["position"]["staff_position_id"]
                == record["position"][
                    "staff_position_id"
                ]  
            ) or (
                record["change_reason_type"]
                and int(record["change_reason_type"])
                == ChangeReasonType.technical.value
                and prev_record["per_no"] == record["per_no"]
            ):
                prev_record = record
                records_to_perform_creation.append(record)
                continue
            else:
                try:
                    self._intent_to_create_card(records_to_perform_creation)
                except Exception as e:

                    logger.error(
                        f"Autogeneration erorr. Details: {per_no}: {type(e), e.with_traceback(None)}"
                    )
                    self.results[CardActivity.errors.value] += 1

            prev_record = record
            records_to_perform_creation = [record]
        try:
            if records_to_perform_creation:
                self._intent_to_create_card(records_to_perform_creation)

        except Exception as e:
            logger.error(
                f"Autogeneration error. Details: {per_no}: {type(e), e.with_traceback(None)}"
            )
            self.results[CardActivity.errors.value] += 1

        self.employee_deactivate_manager.check_cards_for_deactivation(
            per_no, self.employee_fired[per_no], self.employee_cards[per_no]
        )
