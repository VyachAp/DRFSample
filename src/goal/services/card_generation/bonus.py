from datetime import datetime
from typing import Dict, List

from src.goal.models import Period
from src.goal.services.card_generation.bonus_condition import BonusConditionManager


class BonusHandler:
    def __init__(self, period: Period):
        self._period = period
        self.bonus_types = self._period.bonus_types

    @staticmethod
    def _dttm_from_str_to_date(str_dttm):
        return datetime.strptime(str_dttm, "%Y-%m-%d %H:%M:%S").date()

    @staticmethod
    def have_intersection(dates_1, dates_2):
        return (dates_1[0] <= dates_2[0] <= dates_1[1]) or (
            dates_2[0] <= dates_1[0] <= dates_2[1]
        )

    def get_bonus_dates_type(self, bonus):
        bonus_start_dt = self._dttm_from_str_to_date(bonus["business_from_dttm"])
        bonus_end_dt = self._dttm_from_str_to_date(bonus["business_to_dttm"])
        bonus_type = bonus["bonus_type"]
        return bonus_start_dt, bonus_end_dt, bonus_type

    def find_record_bonus_periods(self, bonus_records: List[Dict], hierarchy_txt: str):
        bonus_periods = []
        bonus_start_dt = None
        bonus_end_dt = None
        bonus_type = None

        hierarchy_list = hierarchy_txt.split("\\\\")
        hierarchy_list.reverse()
        business_unit = hierarchy_list[0]

        for bonus in bonus_records:
            if BonusConditionManager(
                period=self._period, unit_hierarchy=hierarchy_list, bonus_record=bonus
            ).is_bonus_appropriate():
                if not bonus_start_dt:  # Фиксируем дату начала действия бонусов
                    (
                        bonus_start_dt,
                        bonus_end_dt,
                        bonus_type,
                    ) = self.get_bonus_dates_type(bonus)
                    continue
                if (
                    bonus["bonus_type"] != bonus_type
                ):  # Если сменился тип бонуса среди тех, кто попадает под условие, то периоды надо разделить
                    bonus_periods.append(
                        {
                            "start": bonus_start_dt,
                            "end": bonus_end_dt,
                            "type": bonus_type,
                            "business_unit": business_unit,
                        }
                    )
                    (
                        bonus_start_dt,
                        bonus_end_dt,
                        bonus_type,
                    ) = self.get_bonus_dates_type(bonus)
                    continue
                _, bonus_end_dt, _ = self.get_bonus_dates_type(bonus)
        # Добавить последний период
        if bonus_start_dt and bonus_end_dt:
            bonus_periods.append(
                {
                    "start": bonus_start_dt,
                    "end": bonus_end_dt,
                    "type": bonus_type,
                    "business_unit": business_unit,
                }
            )

        return bonus_periods

    def merge_bonus_periods(self, current_bonuses, new_bonuses):
        last_bonus = current_bonuses[-1]
        for index, bonus in enumerate(new_bonuses):
            if last_bonus["type"] == bonus["type"]:
                last_bonus["end"] = bonus["end"]
                last_bonus["business_unit"] = bonus["business_unit"]
            else:
                current_bonuses.append(bonus)
                last_bonus = bonus
        return current_bonuses

    def find_bonus_periods(self, historical_records):
        bonus_periods = []
        for record in historical_records:
            record_bonus_periods = self.find_record_bonus_periods(
                record["bonus"], record["division"]["hierarchy_txt"]
            )
            if record_bonus_periods:
                if not bonus_periods:
                    bonus_periods.extend(record_bonus_periods)
                    continue
                bonus_periods = self.merge_bonus_periods(
                    bonus_periods, record_bonus_periods
                )
        return bonus_periods

    def intersect_dates(self, bonus_dates, card_dates):
        """
        Bonus_dates - list of dicts
        [{'start': date_start,'end': date_end,'type': bonus_type, 'business_unit': business_unit},...]
         when bonus exists
        Card_dates - tuple of (card_date_start, card_date_end)
        """

        result_dates = []
        for bonus_date in bonus_dates:
            bonus_period = (bonus_date["start"], bonus_date["end"])
            if self.have_intersection(bonus_period, card_dates):
                res_date_start = max(bonus_period[0], card_dates[0])
                res_date_end = min(bonus_period[1], card_dates[1])
                result_dates.append(
                    {
                        "start": res_date_start,
                        "end": res_date_end,
                        "type": bonus_date["type"],
                        "business_unit": bonus_date["business_unit"],
                    }
                )
        return result_dates

    def apply_bonus_dates(self, historical_records, card_dates):
        bonus_periods = self.find_bonus_periods(historical_records)
        return self.intersect_dates(bonus_periods, card_dates)
