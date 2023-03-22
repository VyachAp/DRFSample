import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple

from src.goal.integrations.camunda import send_message
from src.goal.models import Card, Period
from src.goal.services.card_generation.consts import EmployeeStatus


logger = logging.getLogger(__name__)


def str_dttm_to_date(str_dttm: str) -> date:
    return datetime.strptime(
        str_dttm,
        "%Y-%m-%dT%H:%M:%S%z",
    ).date()


class DeactivateException(Exception):
    pass


class BasicDeactivateManager:
    @staticmethod
    def deactivate_card(card: Card, state: str, date_end: datetime) -> Optional[bool]:
        """Деактивирует карту `card`"""
        previous_state = card.state
        prev_date_end = card.date_end
        card.state = state
        card.date_end = date_end
        card.save(update_fields=["state", "date_end"])
        if (
            (
                card.stage in (card.ON_SETTING.key, card.ON_ACTUALIZATION.key)
                and card.status == card.APPROVED.key
            )
            or card.assessment.assessment_status == card.assessment.APPROVED
            or previous_state == card.NON_ACTIVE.key
        ):
            # Постановка и оценка утверждена, в камунде процесса не должно быть,
            # сообщение не шлём, а также если перевели карту из состояния неактивного в уволенного
            return True
        try:
            send_message(
                business_key=f"cardAgreement_{card.pk}",
                message_name=f"CardDeactivate-{card.pk}",
            )
            if card.status != card.APPROVED.key:
                card.history_approval.all().delete()

            return True
        except Exception as e:
            logger.error(
                f"Ошибка при отправке сообщения деактивации карты {card.pk}: {type(e), e}"
            )
            card.state = previous_state
            card.date_end = prev_date_end
            card.save(update_fields=["state", "date_end"])
            return False


class EmployeeCardDeactivateManager(BasicDeactivateManager):
    def __init__(self, period: Period):
        self.period = period
        self.deactivated_cards_counter = 0
        self.deactivation_errors_counter = 0

    def find_employee_quit_data(
        self, historical_records: List[Optional[Dict]]
    ) -> List[Tuple[date, str]]:
        results = []
        for index, record in enumerate(historical_records):
            if (
                record["position"]["employee_status"] == EmployeeStatus.fired.value
                and str_dttm_to_date(record["business_from_dttm"])
                <= self.period.cards_bonus_payout_date
            ):
                current_record = record
                current_record_start = str_dttm_to_date(record["business_from_dttm"])

                if len(historical_records) > index + 1:
                    # Если сотрудник увольнялся и возвращался,
                    # то после записи об увольнении надеемся найти запись о переустройстве
                    tmp_index = index + 1
                    while tmp_index < len(historical_records):
                        if (
                            historical_records[tmp_index]["position"]["employee_status"]
                            == EmployeeStatus.active.value
                        ):
                            # Записей в состоянии "Уволен" может быть несколько подряд,
                            # нам нужна только следующая активная запись
                            next_record_start = str_dttm_to_date(
                                historical_records[tmp_index]["business_from_dttm"]
                            )
                            # Проверяем даты переустройства
                            if (next_record_start - current_record_start).days > 14:
                                # Если переустройство произошло позднее 14-ти дневного периода,
                                # то считаем, что сотрудник уволился
                                results.append(
                                    (
                                        min(
                                            self.period.date_end,
                                            date.fromisoformat(
                                                current_record["fire_dt"]
                                            ),
                                        ),
                                        Card.NON_ACTIVE_Q.key,
                                    )
                                )
                            break

                        tmp_index += 1
                else:
                    results.append(
                        (
                            min(
                                self.period.date_end,
                                date.fromisoformat(current_record["fire_dt"]),
                            ),
                            Card.NON_ACTIVE_Q.key,
                        )
                    )
        # На выходе получаем список из кортежей, (ДАТА, Состояние) карты.
        # Предполагается итерироваться по списку карт, и если дата окончания карты меньше даты из текущего списка,
        # то присвоить ей состояние из кортежа, в противном случае перейти к следующему кортежу
        return results

    def check_cards_for_deactivation(
        self,
        employee_perno: str,
        employee_quit_data: Optional[List[Tuple]],
        exclude_card_ids: Optional[Set] = None,
    ):
        employee_cards = (
            Card.objects.filter(  # Possible transition: Non-Active -> Non-Active-Q
                period=self.period,
                perno=employee_perno,
            ).exclude(state__in=(Card.CLOSED.key, Card.NON_ACTIVE_Q.key))
        )
        if exclude_card_ids:
            employee_cards = employee_cards.exclude(pk__in=list(exclude_card_ids))

        for card in employee_cards:
            if employee_quit_data:
                # Если данные по увольнениям есть, то состояние карты может варьироваться
                for data in employee_quit_data:
                    if card.date_start < data[0]:
                        deactivation = self.deactivate_card(
                            card, data[1], min(card.date_end, data[0])
                        )
                        if deactivation:
                            self.deactivated_cards_counter += 1
                        else:
                            self.deactivation_errors_counter += 1
                        break
            else:
                deactivation = self.deactivate_card(
                    card, Card.NON_ACTIVE.key, card.date_end
                )
                if deactivation:
                    self.deactivated_cards_counter += 1
                else:
                    self.deactivation_errors_counter += 1


class UnitCardDeactivateManager(BasicDeactivateManager):
    def __init__(self, period: Period):
        self.period = period
        self.deactivated_cards_counter = 0
        self.deactivation_errors_counter = 0

    @staticmethod
    def unpack_card_ids(card_ids: List[Set]):
        result = []
        for ids in card_ids:
            list_value = list(ids)
            result.extend(list_value)
        return result

    def check_cards_for_deactivation(self, card_ids: List[Set], business_unit: str):
        not_related_unit_cards = (
            Card.actual.filter(period=self.period, business_unit=business_unit)
            .exclude(state=Card.CLOSED.key)
            .exclude(pk__in=list(card_ids))
        )

        for card in not_related_unit_cards:
            deactivation = self.deactivate_card(
                card, Card.NON_ACTIVE.key, card.date_end
            )
            if deactivation:
                self.deactivated_cards_counter += 1
            else:
                self.deactivation_errors_counter += 1
