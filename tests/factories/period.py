from datetime import timedelta, date

import factory
from factory import fuzzy

from src.goal.models.period import Period, PeriodType
from tests.factories.employee import EmployeeBonusTypeFactory


class PeriodTypeFactory(factory.django.DjangoModelFactory):
    name = fuzzy.FuzzyChoice(choices=["Год", "Квартал", "Месяц"])
    is_active = True

    class Meta:
        model = PeriodType
        django_get_or_create = ("name",)


class PeriodFactory(factory.django.DjangoModelFactory):
    year = factory.Faker("pyint", min_value=2015, max_value=2023)
    period = factory.Faker("word", locale="ru_RU")
    is_active = True
    date_start = factory.Faker("date_between", start_date="+2d", end_date="+3d")
    date_end = factory.Faker("date_between", start_date="+5d", end_date="+7d")
    cards_generation_end_date = factory.Faker(
        "date_between", start_date="today", end_date="+5d"
    )
    cards_assessment_end_date = factory.Faker(
        "date_between", start_date="today", end_date="+5d"
    )
    cards_bonus_payout_date = factory.LazyAttribute(
        lambda o: o.date_end - timedelta(days=2)
    )
    worked_days_number = factory.Faker("pyint", min_value=0)
    period_type = factory.SubFactory(PeriodTypeFactory)

    class Meta:
        model = Period
        django_get_or_create = ("period",)


class PeriodYearFactory(PeriodFactory):
    period_type = factory.SubFactory(PeriodTypeFactory, name="Год")
    is_active = True
    date_start = factory.LazyAttribute(lambda o: date(year=o.year, month=1, day=1))
    date_end = factory.LazyAttribute(lambda o: date(year=o.year, month=12, day=31))
    cards_generation_end_date = factory.LazyAttribute(
        lambda o: date(year=o.year, month=10, day=1)
    )


class OrgPreferenceFactory(factory.django.DjangoModelFactory):
    bus_unit_id = factory.Faker("numerify", text="5#######")
    period_type = factory.LazyAttribute(lambda o: o.current_period.period_type)
    current_period = factory.SubFactory(PeriodFactory)

    class Meta:
        model = "goal.OrgPreference"
