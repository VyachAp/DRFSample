from dataclasses import dataclass

from src.goal.models.period import Period
from src.goal.services.card_generation.consts import ParentUnits, PeriodTypes


@dataclass
class Strategies:
    TC5 = "TC5"
    CorpCenter = "CorpCenter"


class BonusConditionManager:
    def __init__(self, period: Period, unit_hierarchy: list, bonus_record: dict):
        self.period = period
        self.bonus_record = bonus_record
        self.hierarchy = unit_hierarchy
        self.tc5_units = (ParentUnits.TC5.value, ParentUnits.AdminTC5.value)
        self.current_strategy = None
        self.methods_to_check = []

    def bonus_greater_than(self, border_value):
        return self.bonus_record["bonus_percent"] > border_value

    def bonus_type_in_settings(self):
        return self.bonus_record["bonus_type"] in list(
            self.period.bonus_types.values_list("key", flat=True).all()
        )

    def define_current_strategy_methods(self):
        if (
            self.period.period_type.name == PeriodTypes.year.value
            and self.current_strategy == Strategies.TC5
        ):
            self.methods_to_check = [
                (self.bonus_type_in_settings, ()),
                (self.bonus_greater_than, (10,)),
            ]
            # TODO: Подумать как вынести этот список в User-Friendly настройки
            return
        self.methods_to_check = [(self.bonus_type_in_settings, ())]

    def define_current_strategy(self):
        for unit in self.hierarchy:
            if unit in self.tc5_units:
                self.current_strategy = Strategies.TC5
                self.define_current_strategy_methods()
                return
        self.current_strategy = Strategies.CorpCenter
        self.define_current_strategy_methods()

    def is_bonus_appropriate(self):
        self.define_current_strategy()
        for checker in self.methods_to_check:
            method, params = checker[0], checker[1]
            if not method(*params):
                return False
        return True

    def get_conditions(self):
        if not self.current_strategy:
            raise ValueError("Define current strategy first!")
