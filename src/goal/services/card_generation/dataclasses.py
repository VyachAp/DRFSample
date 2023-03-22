from dataclasses import dataclass
from datetime import datetime
from typing import List

from .helpers import nested_dataclass


@dataclass
class Position:
    """Описание должности сотрудника."""

    name: str
    description: str
    band_code: str
    band_name: str
    position_code: str
    position_name: str
    employment_rate: int
    employee_group: int
    employee_group_desc: str
    staff_position_id: str


@dataclass
class Division:
    """Описание организации сотрудника."""

    name: str
    unit: str
    organizational_unit_desc: str
    parent: str
    level: str
    hierarchy_txt: str


@dataclass
class PositionLog:
    dismissal: bool
    created_at: datetime
    start_vacation: bool
    end_vacation: bool
    start_decree: bool
    end_decree: bool


@nested_dataclass
class Employee:
    """Описание сотрудника."""

    per_no: str
    fullname: str
    bonus: List[dict]
    division: Division
    position: Position
    historical_records: List[dict]
    hired_at: str

    # def was_dismissal(self) -> bool:
    #     return any([log.dismissal for log in self.position_logs])

    # def in_vacation(self) -> bool:
    #     in_vacation_now = True
    #     logs = reversed(sorted(self.position_logs, key=lambda log: log.created_at))
    #
    #     for log in logs:
    #         if log.end_vacation:
    #             return False
    #
    #     return in_vacation_now
    #
    # def worked_days_in_year(self) -> int:
    #     """Получить количество отработанных дней в текущем календарном году."""
    #
    #     def days_between_dates(first_datetime, last_datetime) -> int:
    #         """Получить количество дней между двумя датами"""
    #
    #         if first_datetime > last_datetime:
    #             return abs((first_datetime - last_datetime).days())
    #
    #         return abs((last_datetime - first_datetime).days())
    #
    #     worked_days = days_between_dates(
    #         timezone.now(), timezone.now().date().replace(month=1, day=1)
    #     )
    #     logs = reversed(sorted(self.position_logs, key=lambda log: log.created_at))
    #
    #     for index, log in enumerate(logs):
    #         if log.end_vacation:
    #             Удалить из рабочих дней период отпуска
    # start_vacation_date = log.created_at
    # end_vacation_date = log.created_at
    #
    # for log in logs[index:]:
    #     if log.start_vacation:
    #         start_vacation_date = log.created_at
    #
    # worked_days -= days_between_dates(
    #     start_vacation_date, end_vacation_date
    # )
    # elif log.end_decree:
    #     Удалить из рабочих дней период декрета
    # start_decree_date = log.created_at
    # end_decree_date = log.created_at
    #
    # for log in logs[index:]:
    #     if log.start_decree:
    #         start_decree_date = log.created_at
    #
    # worked_days -= days_between_dates(start_decree_date, end_decree_date)
    #
    # return worked_days


#
