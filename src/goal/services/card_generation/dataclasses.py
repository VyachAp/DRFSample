from dataclasses import dataclass
from datetime import datetime
from typing import List

from .helpers import nested_dataclass


@dataclass
class Position:

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

    per_no: str
    fullname: str
    bonus: List[dict]
    division: Division
    position: Position
    historical_records: List[dict]
    hired_at: str

