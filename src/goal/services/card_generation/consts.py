from enum import Enum


class OrganizationStatus(Enum):
    active = "Активный"
    passive = "Пассивный"


class OrganizationMethod(Enum):
    hourly = "1"
    salary = "2"


class ParentUnits(Enum):
    TC5 = "51047541"
    AdminTC5 = "52692242"
    CorpCentre = "50611734"


class EmployeeStatus(Enum):
    active = "3"
    fired = "0"


class ChangeReasonType(Enum):
    technical = 2


class PeriodTypes(Enum):
    year = "Год"
    half_year = "Полгода"
    quarter = "Квартал"
    month = "Месяц"


class CardActivity(Enum):
    reactivated = "reactivated"
    checked = "checked"
    updated = "updated"
    created = "created"
    errors = "errors"
