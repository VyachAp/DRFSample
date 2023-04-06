import abc
from datetime import date, datetime
from functools import lru_cache
from typing import Dict, List

from src.goal.models.period import Period

from .consts import OrganizationMethod


class FilterEmployee:
    """
    We need to check out if employee is suitable for card generation with hise historical records slice
    """

    def __init__(self, dates: Dict, employee_records: List[Dict], period):
        """
        dates - {"start": Date start, "end": Date end}

        employee_records - List of employee historical records
        """
        self.dates = dates
        self.employee_records = employee_records
        self.period = period

    def is_suited(self) -> bool:
        if self.suitable_by_position_status(
            self.employee_records, self.period, self.dates
        ) and self.suitable_by_position(self.employee_records, self.period, self.dates):
            return True
        return False

    @staticmethod
    def suitable_by_position(employee, period, dates):
        return PositionFilter(employee, period, dates).is_suitable_employee()

    @staticmethod
    def suitable_by_position_status(employee, period, dates):
        return PositionStatusFilter(employee, period, dates).is_suitable_employee()


class SuitableFilter(abc.ABC):

    def __init__(self, employee: List[Dict], period: Period, dates: Dict):
        self.employee = employee
        self.period = period
        self.dates = dates

    @abc.abstractmethod
    def is_suitable_employee(self) -> bool:
        pass

    @staticmethod
    def _dttm_from_str_to_date(str_dttm):
        return datetime.strptime(str_dttm, "%Y-%m-%dT%H:%M:%S%z").date()

    @staticmethod
    def have_intersection(dates_1, dates_2):
        return (dates_1[0] <= dates_2[0] <= dates_1[1]) or (
            dates_2[0] <= dates_1[0] <= dates_2[1]
        )

    @lru_cache()
    def find_appropriate_records(self):
        result = []
        card_dates = (self.dates["start"], self.dates["end"])
        for record in self.employee:
            record_dates = (
                self._dttm_from_str_to_date(record["business_from_dttm"]),
                self._dttm_from_str_to_date(record["business_to_dttm"]),
            )
            if self.have_intersection(record_dates, card_dates):
                result.append(record)
        return result


class PositionFilter(SuitableFilter):
    def is_suitable_employee(self) -> bool:
        return self._rate() and self._method()

    def _rate(self) -> bool:
        for record in self.find_appropriate_records():
            if (
                record["position"]["employment_rate"]
                and record["position"]["employment_rate"] > 0
            ):
                return True
        return False

    def _method(self) -> bool:
        for record in self.find_appropriate_records():
            if record["position"]["employee_group"] in (
                OrganizationMethod.hourly.value,
                OrganizationMethod.salary.value,
            ):
                return True
        return False


class PositionStatusFilter(SuitableFilter):
    def is_suitable_employee(self) -> bool:
        return self._hired_at()

    def _hired_at(self) -> bool:
        # All hire_dt in self.employee are the same, so take the first one as definition mark
        return (
            date.fromisoformat(self.employee[0]["hire_dt"])
            <= self.period.cards_generation_end_date
        )
