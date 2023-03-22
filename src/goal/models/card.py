import datetime
import decimal

from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils.functional import cached_property

from src.goal.integrations.hr.hr_edw import (
    get_last_orgstructure,
    get_profile,
    get_sup_managers,
)
from src.goal.models.enums import APPROVAL_ROLES
from src.goal.models.extensions.card import (
    get_corp_goals,
    get_org_parameter,
    get_org_triggers,
    get_unit_goals,
)
from src.goal.models.extensions.card_assessment import (
    calculate_final_goal_percentage,
    define_bonus_periods,
    get_employee_bonuses,
)
from src.goal.models.extensions.card_properties import CardStage, CardState, CardStatus
from src.goal.models.kpi import PersonalCorrectiveKpiAssessment
from src.goal.models.orgstructure import Orgstructure
from src.goal.models.trigger import Trigger
from src.helpers.exceptions.drf import SerializingError


class ActualCardManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(state__in=(Card.NON_ACTIVE.key, Card.NON_ACTIVE_Q.key))
        )


class StartCardActionManager(models.Manager):
    """Карты которые можно назначить"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status=Card.CREATED.key,
                assessment__assessment_status=CardsAssessment.NOT_STARTED,
            )
        )

    @staticmethod
    def can_be_started(card) -> bool:
        """Карту можно назначить"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status == card.CREATED.key
            and card.assessment.assessment_status == CardsAssessment.NOT_STARTED
        )


class ActualizeCardActionManager(models.Manager):
    """Карты которые можно актуализировать"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status=Card.APPROVED.key,
                assessment__assessment_status__in=[
                    CardsAssessment.NOT_STARTED,
                    CardsAssessment.APPROVED,
                ],
            )
        )

    @staticmethod
    def can_be_actualized(card) -> bool:
        """Карту можно актуализировать"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status == card.APPROVED.key
            and card.assessment.assessment_status
            in (
                CardsAssessment.NOT_STARTED,
                CardsAssessment.APPROVED,
            )
        )


class AssessmentCardActionManager(ActualizeCardActionManager):
    """Карты которые можно оценить

    Аналогично актуализации
    """

    @staticmethod
    def can_be_assessed(card) -> bool:
        """Карту можно актуализировать"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status == card.APPROVED.key
            and card.assessment.assessment_status
            in (
                CardsAssessment.NOT_STARTED,
                CardsAssessment.APPROVED,
            )
        )


class ApproveForceActionManager(models.Manager):
    """Карты которые можно утвердить"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status__in=[
                    Card.CREATED.key,
                    Card.NOT_STARTED.key,
                    Card.IN_WORK.key,
                    Card.AGREEMENT.key,
                    Card.FAMILIARIZATION.key,
                ],
                assessment__assessment_status=CardsAssessment.NOT_STARTED,
            )
        )

    @staticmethod
    def can_be_approved_force(card) -> bool:
        """Можно утвердить карту"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status
            in (
                card.CREATED.key,
                card.NOT_STARTED.key,
                card.IN_WORK.key,
                card.AGREEMENT.key,
                card.FAMILIARIZATION.key,
            )
            and card.assessment.assessment_status == CardsAssessment.NOT_STARTED
        )


class AssessmentInterruptActionManager(models.Manager):
    def get_queryset(self):
        """Карты у которых можно прервать оценку"""
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status=Card.APPROVED.key,
                assessment__assessment_status__in=[
                    CardsAssessment.IN_PROGRESS,
                    CardsAssessment.ON_APPROVEMENT,
                ],
            )
        )

    @staticmethod
    def can_be_assessment_interrupted(card) -> bool:
        """Можно прервать оценку карты"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status == card.APPROVED.key
            and card.assessment.assessment_status
            in (
                CardsAssessment.IN_PROGRESS,
                CardsAssessment.ON_APPROVEMENT,
            )
        )


class AssessmentApproveActionManager(models.Manager):
    def get_queryset(self):
        """Карты у которых можно утвердить оценку карты

        Важно! Этот qs неполный, необходимо ещё проверить условие в
        can_be_assessment_approved
        """
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status=Card.APPROVED.key,
                assessment__assessment_status=CardsAssessment.IN_PROGRESS,
            )
        )

    @staticmethod
    def can_be_assessment_approved(card) -> bool:
        """Можно принудительно утвердить оценку карты"""
        if not (
            card.state == card.ACTIVE.key
            and card.status == card.APPROVED.key
            and card.assessment.assessment_status == CardsAssessment.IN_PROGRESS
        ):
            return False
        # Если индивидуальный блок не предусмотрен
        try:
            goal_weight_template = get_org_parameter(card=card)
        except SerializingError:
            return False
        if not goal_weight_template:
            return False
        return not goal_weight_template[0].is_personal_kpi_enable


class CloseActionManager(models.Manager):
    def get_queryset(self):
        """Карты которые можно закрыть"""
        return (
            super()
            .get_queryset()
            .filter(
                state=Card.ACTIVE.key,
                status=Card.APPROVED.key,
                assessment__assessment_status=CardsAssessment.APPROVED,
            )
        )

    @staticmethod
    def can_be_closed(card) -> bool:
        """Можно закрыть карту"""
        return bool(
            card.state == card.ACTIVE.key
            and card.status == card.APPROVED.key
            and card.assessment.assessment_status == CardsAssessment.APPROVED
        )


class OpenActionManager(models.Manager):
    def get_queryset(self):
        """Карты которые можно открыть"""
        return super().get_queryset().filter(state=Card.CLOSED.key)

    @staticmethod
    def can_be_opened(card) -> bool:
        """Можно открыть карту"""
        return bool(card.state == card.CLOSED.key)


class Card(models.Model):
    """Модель персональных карт"""

    objects = models.Manager()
    actual = ActualCardManager()

    objects_can_be_started = StartCardActionManager()
    objects_can_be_actualized = ActualizeCardActionManager()
    objects_can_be_assessed = AssessmentCardActionManager()
    objects_can_be_approved_force = ApproveForceActionManager()
    objects_can_be_assessment_interrupted = AssessmentInterruptActionManager()
    # важно! objects_maybe_can_be_assessment_approved - неполное условие, необходимо ещё
    # проверить что индивидуальный блок не предусмотрен
    objects_maybe_can_be_assessment_approved = AssessmentApproveActionManager()
    objects_can_be_closed = CloseActionManager()
    objects_can_be_opened = OpenActionManager()

    # Возможные статусы карты
    CREATED = CardStatus("карта создана", "Created", "#BBBBBB")
    NOT_STARTED = CardStatus("карта не начата", "Not started", "#EC5A57")
    IN_WORK = CardStatus("карта в работе", "In work", "#F1A15C")
    FAMILIARIZATION = CardStatus("карта на ознакомлении", "Familiarization", "#F4D05E")
    AGREEMENT = CardStatus("карта на согласовании", "Agreement", "#F4D05E")
    APPROVED = CardStatus("карта утверждена", "Approved", "#71CA7B")
    IS_PROCESSED = CardStatus("обрабатывается", "Is processed", "#BBBBBB")

    # Возможные состояния карт
    ACTIVE = CardState("Активна", "Active")
    NON_ACTIVE = CardState("Не активна", "Non-Active")
    FROZEN = CardState("Заморожена", "Frozen")
    CLOSED = CardState("Закрыта", "Closed")
    NON_ACTIVE_Q = CardState("Уволился", "Non-Active-Q")

    # Возможные этапы согласования карты
    ON_SETTING = CardStage("Постановка", "on_setting")
    ON_ACTUALIZATION = CardStage("Актуализация", "on_actualization")
    ON_ASSESSMENT = CardStage("Оценка", "on_assessment")

    perno = models.CharField("Владелец карты", max_length=30)
    # Орг.единица, в рамках которой оформлена карта
    business_unit = models.CharField("Орг.единица", max_length=50, blank=True)
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=CardStatus.choices(),
        default=IS_PROCESSED.key,
    )
    period = models.ForeignKey(
        "goal.Period", verbose_name="Период", on_delete=models.PROTECT
    )
    date_start = models.DateField("Дата начала действия карты")
    date_end = models.DateField("Дата окончания действия карты")

    dt_created = models.DateTimeField(auto_now_add=True)
    state = models.CharField(
        "Состояние карты",
        max_length=20,
        choices=CardState.choices(),
        default=ACTIVE.key,
    )
    stage = models.CharField(
        "Этап карты",
        max_length=20,
        choices=CardStage.choices(),
        default=ON_SETTING.key,
    )
    comment = GenericRelation("goal.Comment", related_query_name="card")
    bonus_type = models.ForeignKey("EmployeeBonusType", on_delete=models.PROTECT)
    generation_task_id = models.UUIDField("ID задачи", null=True)

    @property
    def status_obj(self):
        return CardStatus.CARD_STATUSES[self.status]

    @property
    def state_obj(self):
        return CardState.CARD_STATES[self.state]

    @property
    def stage_obj(self):
        return CardStage.CARD_STAGES[self.stage]

    @property
    def hierarchy_txt(self):
        return self.employee["division"]["hierarchy_txt"]

    @property
    def date_end_dttm(self):
        # дата окончания карты, по формату аналогичная business_from_dttm
        # и business_to_dttm
        return (
            datetime.datetime(
                self.date_end.year, self.date_end.month, self.date_end.day
            ).isoformat()
            + "Z"
        )

    @cached_property
    def employee(self):
        fields = [
            "division",
            "position",
            "business_from_dttm",
            "business_to_dttm",
            "job_title_id",
            "hire_dt",
            "fire_dt",
            "staff_position_competence_code",
        ]
        profile = get_profile(
            self.perno,
            params={
                "fields": ",".join(fields),
                "date": self.date_end.isoformat(),
            },
        ).copy()

        sup_manager = get_sup_managers(self.perno, only_first=True)
        profile.update(
            {
                "managers": {
                    "type": "superior",
                    "perno": sup_manager.get("manager_perno", ""),
                },
                "division_date": self.date_end_dttm,
            }
        )

        division = profile["division"]
        if "business_from_dttm" in division and "business_to_dttm" in division:
            is_card_date_end_in_range = (
                division["business_from_dttm"]
                < self.date_end_dttm
                < division["business_to_dttm"]
            )
            is_business_unit_different = int(self.business_unit) != int(
                division["unit"]
            )
            if not is_card_date_end_in_range or is_business_unit_different:
                # подразделение из профиля не подходит по параметрам, запрашиваем
                # отдельно
                division = self._get_division()
                profile.update(
                    {
                        "division": division,
                        "division_date": min(
                            division["business_to_dttm"],
                            self.date_end_dttm,
                        ),
                    }
                )
        return profile

    class Meta:
        app_label = "goal"

        verbose_name = "Карта"
        verbose_name_plural = "Карты"
        db_table = "cards"

        ordering = ["date_end", "date_start", "dt_created"]
        unique_together = ("perno", "business_unit", "period", "date_start", "date_end")

    def __str__(self):
        return f"{self.pk}: {self.perno} - {self.business_unit}"

    def _get_division(self):
        # оргструктура на дату окончания карты
        fields = [
            "name",
            "unit",
            "organizational_unit_desc",
            "parent",
            "level",
            "hierarchy_txt",
            "business_from_dttm",
            "business_to_dttm",
        ]
        return get_last_orgstructure(
            url_params={
                "unit": self.business_unit,
                "fields": ",".join(fields),
            },
        )

    def clean_date_start(self):
        if self.date_start < self.period.date_start:
            raise ValidationError(
                f"Дата начала действия карты должна быть >= {self.period.date_start}"
            )

    def clean_date_end(self):
        if self.date_end > self.period.date_end:
            raise ValidationError(
                f"Дата окончания действия карты должна быть <= {self.period.date_end}"
            )

    def clean_date_start_and_date_end(self):
        if self.date_start > self.date_end:
            raise ValidationError(
                f"Дата начала действия карты должна быть <= {self.date_end}"
            )

    def clean_in_work_status(self):
        if self.status in (self.IN_WORK.key, self.NOT_STARTED.key):
            self._set_editable_status()

    def clean(self):
        self.clean_date_start()
        self.clean_date_end()
        self.clean_date_start_and_date_end()
        self.clean_in_work_status()

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        self.full_clean()
        return super().save(force_insert, force_update, using, update_fields)

    @property
    def unit_goals_own(self):
        return self.pers_goals.filter(goal_type="Unit").order_by("id")

    @property
    def corp_goals_own(self):
        return self.pers_goals.filter(goal_type="Corp").order_by("id")

    @property
    def personal_goals(self):
        return self.pers_goals.filter(goal_type="Pers").order_by("id")

    @property
    def personal_parameters(self):
        PersonalParameter = apps.get_model("goal.PersonalParameter")
        return PersonalParameter.objects.filter(card=self)

    def _set_editable_status(self):
        self.status = self.IN_WORK.key if self.personal_goals else self.NOT_STARTED.key

    def set_editable_status(self) -> None:
        if self.status in (self.IN_WORK.key, self.NOT_STARTED.key):
            self._set_editable_status()
            self.save(update_fields=["status"])

    def get_active_date(self):
        today = datetime.date.today()
        if today < self.date_start:
            return self.date_start
        if self.date_start <= today <= self.date_end:
            return today
        if self.date_end < today:
            return self.date_end

    @property
    def recommended_result_assessment(self):
        result = 0
        for goal in self.personal_goals:
            if goal.goal_done_percent is None:
                return None
            result += goal.goal_done_percent * goal.weight / 100
        # по орг структуре находим шкалу результативности и по этой шкале находим
        # рекомендуемую оценку
        _, parameters = Orgstructure(self.business_unit).parameters(self.period.id)
        try:
            result_scale = parameters.individual_matrix_id.personal_result_scale
        except AttributeError:
            return None
        PersonalResultScaleValues = apps.get_model("goal.PersonalResultScaleValues")
        result_scale_values = PersonalResultScaleValues.objects.filter(
            scale=result_scale
        )
        for value in result_scale_values:
            if value.percent_value_from <= result < value.percent_value_to:
                return value.level
        return None

    @property
    def can_be_started(self) -> bool:
        """Карту можно назначить"""
        return StartCardActionManager.can_be_started(self)

    @property
    def can_be_actualized(self) -> bool:
        """Карту можно актуализировать"""
        return ActualizeCardActionManager.can_be_actualized(self)

    @property
    def can_be_assessed(self) -> bool:
        """Можно назначить оценку карты"""
        return AssessmentCardActionManager.can_be_assessed(self)

    @property
    def can_be_approved_force(self) -> bool:
        """Можно утвердить карту"""
        return ApproveForceActionManager.can_be_approved_force(self)

    @property
    def can_be_assessment_interrupted(self) -> bool:
        """Можно прервать оценку карты"""
        return AssessmentInterruptActionManager.can_be_assessment_interrupted(self)

    @property
    def can_be_assessment_approved(self) -> bool:
        """Можно утвердить оценку карты

        Утвердить оценку можно, если индивидуальные цели отключены для карты"""
        return AssessmentApproveActionManager.can_be_assessment_approved(self)

    @property
    def can_be_closed(self) -> bool:
        """Можно закрыть карту"""
        return CloseActionManager.can_be_closed(self)

    @property
    def can_be_opened(self) -> bool:
        """Можно открыть карту"""
        return OpenActionManager.can_be_opened(self)


class CardStatusHistory(models.Model):
    card = models.ForeignKey(
        "goal.Card", related_name="history_status", on_delete=models.CASCADE
    )
    status = models.CharField("Статус", max_length=20)
    start_dt = models.DateTimeField("Дата/Время получения статуса", null=False)
    end_dt = models.DateTimeField("Дата/Время смены текущего статуса", null=True)

    class Meta:
        app_label = "goal"

        verbose_name = "История статуса карты"
        verbose_name_plural = "Истории статусов карт"
        db_table = "cards_status_history"

        unique_together = ("card", "status")


class CardApprovalHistory(models.Model):
    card = models.ForeignKey(
        "goal.Card", related_name="history_approval", on_delete=models.CASCADE
    )
    perno = models.CharField("Согласующий карту", max_length=30)
    approval_dttm = models.DateTimeField(
        "Дата/Время согласования карты", auto_now_add=True
    )
    role = models.CharField(
        "Роль согласовавшего сотрудника", choices=APPROVAL_ROLES, max_length=30
    )

    class Meta:
        app_label = "goal"

        verbose_name = "История согласования карты"
        verbose_name_plural = "Истории согласования карт"
        db_table = "cards_approval_history"


class CardsStageHistory(models.Model):
    """История этапов карты"""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"

    card = models.ForeignKey(
        "goal.Card", related_name="history_stage", on_delete=models.CASCADE
    )
    stage = models.CharField("Этап карты", max_length=20, choices=CardStage.choices())
    start_dt = models.DateTimeField("Дата/Время этапа")
    end_dt = models.DateTimeField("Дата/Время завершения этапа", null=True, blank=True)

    class Meta:
        app_label = "goal"
        verbose_name = "История этапов карты"
        verbose_name_plural = "Истории этапов карт"
        db_table = "cards_stage_history"


class CardProcedureState(models.Model):
    """Модель хранения состояния процедур карт"""

    objects = models.Manager()

    period = models.ForeignKey(
        "goal.Period", verbose_name="Период", on_delete=models.PROTECT
    )
    business_unit = models.CharField("Орг.единица", max_length=50)
    is_generation_enabled = models.BooleanField(
        "Генерация карт разрешена?", default=False
    )
    is_start_enabled = models.BooleanField("Назначение карт разрешено?", default=False)

    class Meta:
        app_label = "goal"

        verbose_name = "Состояние процедур карт"
        verbose_name_plural = "Состояния процедур карт"
        db_table = "org_cards_state"
        unique_together = ("period", "business_unit")


class EmployeeBonusType(models.Model):
    """Модель типов бонусов сотрудников"""

    objects = models.Manager()
    key = models.CharField(max_length=4, unique=True)
    name = models.CharField(max_length=127, blank=True)

    class Meta:
        app_label = "goal"

        verbose_name = "Тип бонуса сотрудника"
        verbose_name_plural = "Типы бонусов сотрудников"
        db_table = "employee_bonus_types"

    def __str__(self):
        return f"{self.key}"


class CardsAssessment(models.Model):
    """Модель оценок карты"""

    NOT_STARTED = "NotStarted"
    IN_PROGRESS = "InProgress"
    ON_APPROVEMENT = "OnApprovement"
    APPROVED = "Approved"
    IS_PROCESSED = "IsProcessed"

    ASSESSMENT_STATUSES = [
        (NOT_STARTED, "Не начата"),
        (IN_PROGRESS, "В работе"),
        (ON_APPROVEMENT, "На согласовании"),
        (APPROVED, "Согласована"),
        (IS_PROCESSED, "Обрабатывается"),
    ]

    objects = models.Manager()
    own_result_assessment = models.CharField(
        "Собственная оценка результативности", blank=True, max_length=32
    )
    func_result_assessment = models.CharField(
        "Оценка результативности функционального руководителя",
        blank=True,
        max_length=32,
    )
    adm_result_assessment = models.CharField(
        "Оценка результативности административного руководителя",
        blank=True,
        max_length=32,
    )
    own_competence_assessment = models.CharField(
        "Собственная оценка компетентности", blank=True, max_length=32
    )
    func_competence_assessment = models.CharField(
        "Оценка компетентности функционального руководителя",
        blank=True,
        max_length=32,
    )
    adm_competence_assessment = models.CharField(
        "Оценка компетентности административного руководителя",
        blank=True,
        max_length=32,
    )
    personnel_kpi_done_percent = models.DecimalField(
        "Процент выполнения КПЭ",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.01),
        ],
    )
    corp_kpi_final = models.DecimalField(
        "Итоговый процент выполнения корпоративных целей",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    unit_kpi_final = models.DecimalField(
        "Итоговый процент выполнения целей подразделения",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    personnel_kpi_final = models.DecimalField(
        "Итоговый процент выполнения индивидуальных целей",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    common_kpi_final = models.DecimalField(
        "Общий итоговый процент без учета целей корп. и подр.",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    corrective_kpi_final = models.DecimalField(
        "Cуммарная оценка корр.КПЭ",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    trigger_final = models.IntegerField(
        "Результат произведения оценок триггеров", null=True, blank=True
    )
    card_kpi_final = models.DecimalField(
        "Итоговый процент КПЭ карты",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    individual_matrix_value = models.ForeignKey(
        "goal.IndividualMatrixValues", on_delete=models.PROTECT, null=True, blank=True
    )
    assessment_status = models.CharField(
        "Статус оценки", choices=ASSESSMENT_STATUSES, max_length=32, default=NOT_STARTED
    )
    card = models.OneToOneField(
        "goal.Card", on_delete=models.CASCADE, related_name="assessment"
    )

    class Meta:
        app_label = "goal"

        verbose_name = "Оценка карты"
        verbose_name_plural = "Оценки карт"
        db_table = "cards_assessments"

    def __str__(self):
        return f"{self.pk} - {self.card}"

    def calculate_corrective_kpi_final(self):
        pers_corr_kpis = PersonalCorrectiveKpiAssessment.objects.filter(
            card=self.card
        ).aggregate(total_sum=Sum("corrective_kpi_assessment"))["total_sum"]
        if pers_corr_kpis:
            return decimal.Decimal(pers_corr_kpis)

    def calculate_trigger_final(self):
        org_triggers = get_org_triggers(self.card)
        if not org_triggers:
            return None
        for org_trigger in org_triggers:
            if not org_trigger.trigger_assessment:
                return 0
            if org_trigger.trigger.way_to_achieve == Trigger.GREATER_BETTER:
                if org_trigger.trigger_assessment < decimal.Decimal(org_trigger.value):
                    return 0
            else:
                if (
                    org_trigger.trigger_assessment
                    and org_trigger.trigger_assessment
                    > decimal.Decimal(org_trigger.value)
                ):
                    return 0
        return 1

    def calculate_bonuses(self):
        card = self.card
        goal_weight_template = get_org_parameter(card)
        if not goal_weight_template:
            return
        goal_weight_template = goal_weight_template[0]

        matrix_value = self.individual_matrix_value

        if matrix_value and matrix_value.min_bonus == matrix_value.max_bonus:
            # выбрать процент выполнения нельзя, задаем сразу
            self.personnel_kpi_done_percent = matrix_value.min_bonus

        if matrix_value and matrix_value.entire_card:
            self.common_kpi_final = (
                self.personnel_kpi_done_percent
                if self.personnel_kpi_done_percent
                else 0
            )
            self.personnel_kpi_final = None
            self.corp_kpi_final = None
            self.unit_kpi_final = None
            self.card_kpi_final = self.common_kpi_final
        else:
            self.common_kpi_final = None

            if (
                self.personnel_kpi_done_percent
                and goal_weight_template
                and goal_weight_template.is_personal_kpi_enable
            ):
                self.personnel_kpi_final = (
                    self.personnel_kpi_done_percent
                    * goal_weight_template.personal_kpi_weight
                    / 100
                )
            elif goal_weight_template and goal_weight_template.is_personal_kpi_enable:
                self.personnel_kpi_final = 0
            else:
                self.personnel_kpi_final = None

            if goal_weight_template and goal_weight_template.is_corp_kpi_enable:
                self.corp_kpi_final = calculate_final_goal_percentage(
                    get_corp_goals(card), goal_weight_template, "corp_kpi_weight"
                )
            else:
                self.corp_kpi_final = None

            if goal_weight_template and goal_weight_template.is_unit_kpi_enable:
                self.unit_kpi_final = calculate_final_goal_percentage(
                    get_unit_goals(card), goal_weight_template, "unit_kpi_weight"
                )
            else:
                self.unit_kpi_final = None

            self.card_kpi_final = (
                (decimal.Decimal(self.corp_kpi_final) if self.corp_kpi_final else 0)
                + (decimal.Decimal(self.unit_kpi_final) if self.unit_kpi_final else 0)
                + (
                    decimal.Decimal(self.personnel_kpi_final)
                    if self.personnel_kpi_final
                    else 0
                )
            )

        self.corrective_kpi_final = (
            self.calculate_corrective_kpi_final()
            if goal_weight_template.corrective_kpi
            else None
        )
        if goal_weight_template.corrective_kpi and self.corrective_kpi_final:
            self.card_kpi_final += self.corrective_kpi_final

        self.trigger_final = (
            self.calculate_trigger_final() if goal_weight_template.triggers else None
        )
        if goal_weight_template.triggers and self.trigger_final is not None:
            self.card_kpi_final *= self.trigger_final

        # NOTE: TEMP ROUND FIX
        self.card_kpi_final = round(self.card_kpi_final, 1)
        if self.corp_kpi_final:
            self.corp_kpi_final = round(self.corp_kpi_final, 1)

        self.save()
        self.create_relative_bonus_records()

    def create_relative_bonus_records(self):
        params = {
            "fields": "historical_records",
        }
        employee_records = get_profile(self.card.perno, params)

        employee_bonus = get_employee_bonuses(
            employee_records, self.card.date_start, self.card.date_end
        )
        bonus_periods = define_bonus_periods(self.card, employee_bonus)
        for bonus_period in bonus_periods:
            bonus_percent = (
                bonus_period["bonus_addition_pct"] * self.card_kpi_final / 100
            )
            bonus_period["card"] = self.card
            bonus, _ = CardBonuses.objects.get_or_create(**bonus_period)
            # Вынесено ниже, чтобы не создавать дублирующиеся записи, если была пересчитана оценка
            bonus.bonus_percent = bonus_percent
            bonus.save()


class CardBonuses(models.Model):
    start_dt = models.DateField("Дата начала действия бонуса")
    end_dt = models.DateField("Дата окончания действия бонуса")
    bonus_addition_pct = models.DecimalField(
        "Базовый процент бонуса",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    bonus_percent = models.DecimalField(
        "Итоговый процент бонуса",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    card = models.ForeignKey(
        "goal.Card", on_delete=models.CASCADE, related_name="bonuses"
    )

    class Meta:
        app_label = "goal"

        verbose_name = "Бонус карты"
        verbose_name_plural = "Бонусы карт"
        db_table = " cards_bonuses"

    def __str__(self):
        return f"{self.pk} - {self.bonus_percent}:{self.card}"
