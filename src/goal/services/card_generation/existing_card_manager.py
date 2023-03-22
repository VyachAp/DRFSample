import logging

from src.goal.models.card import Card, CardsStageHistory, EmployeeBonusType
from src.goal.models.extensions.camunda import start_process
from src.goal.services.card_generation.consts import CardActivity


logger = logging.getLogger(__name__)


class ExistingCardManager:
    def __init__(self, card):
        self.card = card

    def reactivate_card(self) -> bool:
        last_stage = (
            CardsStageHistory.objects.filter(card=self.card)
            .order_by("-start_dt")
            .first()
        )
        if not last_stage:
            logger.warning("Attempt to reactivate weird card")
            return False

        if last_stage.end_dt is None:
            self.card.state = Card.ACTIVE.key
            if last_stage.stage in (self.card.ON_SETTING, self.card.ON_ACTUALIZATION):
                prev_status = self.card.status
                self.card.status = self.card.IS_PROCESSED.key
            if last_stage.stage == self.card.ON_ASSESSMENT:
                prev_assessment_status = self.card.assessment.assessment_status
                self.card.assessment.assessment_status = (
                    self.card.assessment.IS_PROCESSED
                )
            self.card.save(update_fields=["state", "status"])
            try:
                start_process(self.card, last_stage.stage)
                return True
            except Exception as e:
                self.card.state = Card.NON_ACTIVE.key
                if last_stage.stage in (
                    self.card.ON_SETTING,
                    self.card.ON_ACTUALIZATION,
                ):
                    self.card.status = prev_status
                if last_stage.stage == self.card.ON_ASSESSMENT:
                    self.card.assessment.assessment_status = prev_assessment_status
                self.card.save(update_fields=["state", "status"])
                logger.error(
                    f"Не удалось ре-активировать карту {self.card.pk}. Reason: {e}"
                )
        else:
            self.card.state = Card.ACTIVE.key
            self.card.save(update_fields=["state"])
            # Stage завершен, необходимо восстановить лишь состояние карты
            # без восстановления процесса в камунде
            return True

    def handle_existing_card(self, dates):
        date_end = dates["end"]
        bonus_type = EmployeeBonusType.objects.get(key=dates["type"])

        if self.card.state in (
            Card.NON_ACTIVE.key,
            Card.NON_ACTIVE_Q.key,
        ):  # Если нашли де-активированную карту, то ее необходимо активировать
            is_reactivated = self.reactivate_card()
            if is_reactivated:
                self.card.date_end = date_end
                self.card.bonus_type = bonus_type
                self.card.business_unit = dates["business_unit"]
                self.card.save(
                    update_fields=["date_end", "bonus_type", "business_unit"]
                )
                return CardActivity.reactivated.value
        if (
            self.card.date_end == date_end
            and self.card.bonus_type == bonus_type
            and self.card.business_unit == dates["business_unit"]
        ):
            # Карта не изменилась, ничего не делаем
            return CardActivity.checked.value

        if self.card.state != Card.CLOSED.key:
            # Карта не закрыта, можем обновить ее
            self.card.date_end = date_end
            self.card.bonus_type = bonus_type
            self.card.business_unit = dates["business_unit"]
            self.card.save(update_fields=["date_end", "bonus_type", "business_unit"])

            return CardActivity.updated.value
