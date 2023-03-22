import factory
from django.db.models.signals import post_save

from src.goal.models.card import Card, CardsAssessment
from src.goal.models.extensions.card_properties import CardStage, CardState
from tests.factories.period import PeriodFactory
from tests.factories.employee import EmployeeBonusTypeFactory


class CardFactory(factory.django.DjangoModelFactory):
    perno = factory.Faker("numerify", text="%######")
    business_unit = factory.Faker("numerify", text="5#######")
    status = Card.IS_PROCESSED.key
    state = factory.Faker(
        "random_element", elements=[st for st in CardState.CARD_STATES.keys()]
    )
    stage = factory.Faker(
        "random_element", elements=[stg for stg in CardStage.CARD_STAGES.keys()]
    )
    period = factory.SubFactory(
        PeriodFactory,
        date_start=factory.Faker("date_between", start_date="-5d", end_date="-4d"),
        date_end=factory.Faker("date_between", start_date="+14d", end_date="+15d"),
    )
    date_start = factory.Faker("date_between", start_date="today", end_date="+1d")
    date_end = factory.Faker("date_between", start_date="+5d", end_date="+8d")
    dt_created = factory.Faker("date_time_this_month")
    bonus_type = factory.SubFactory(EmployeeBonusTypeFactory)
    generation_task_id = factory.Faker("uuid4")

    class Meta:
        model = Card


@factory.django.mute_signals(post_save)
class CardNoSignalFactory(CardFactory):
    pass


class CardsAssessmentFactory(CardFactory):
    card = factory.SubFactory(CardFactory)

    class Meta:
        model = CardsAssessment
