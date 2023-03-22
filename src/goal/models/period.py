from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models


DEFAULT_DATA = datetime(1970, 1, 1)


class PeriodType(models.Model):
    objects = models.Manager()

    name = models.CharField("Название", max_length=50, unique=True)
    is_active = models.BooleanField("Статус активности", default=True)
    bonus_types = models.ManyToManyField("goal.EmployeeBonusType")

    class Meta:
        app_label = "goal"

        verbose_name = "Тип периода целеполагания"
        verbose_name_plural = "Типы периодов целеполагания"
        db_table = "period_type"

    def __str__(self):
        return f"{self.name}"


class Period(models.Model):
    objects = models.Manager()

    year = models.PositiveSmallIntegerField("Год целеполагания")
    period = models.CharField("Период", max_length=16, unique=True)
    is_active = models.BooleanField("Статус активности", default=True)

    date_start = models.DateField("Дата начала периода")
    date_end = models.DateField("Дата окончания периода")
    period_type = models.ForeignKey(
        PeriodType,
        verbose_name="Тип периода",
        on_delete=models.PROTECT,
    )
    bonus_types = models.ManyToManyField("goal.EmployeeBonusType")

    cards_generation_end_date = models.DateField("Дата прекращения создания карт")
    cards_assessment_end_date = models.DateField("Дата окончания оценки")
    cards_bonus_payout_date = models.DateField("Дата выгрузки для выплаты премии")
    worked_days_number = models.PositiveIntegerField("Количество отработанных дней")

    class Meta:
        app_label = "goal"

        verbose_name = "Период целеполагания"
        verbose_name_plural = "Периоды целеполагания"
        db_table = "periods"

    def __str__(self):
        return f"{self.pk}: {self.period}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        self.clean_date_start_and_date_end()
        self.clean_cards_generation_end_date()

    def clean_date_start_and_date_end(self):
        if self.date_start >= self.date_end:
            raise ValidationError(
                f"Дата окончания периода должна быть > {self.date_start}"
            )

    def clean_cards_generation_end_date(self):
        if self.cards_generation_end_date > self.date_end:
            raise ValidationError(
                f"Дата прекращения создания карт должна быть <= {self.date_end}"
            )

    @staticmethod
    def actual_periods() -> dict:
        """Актуальный текущий период - первый активный период (по времени)"""
        actual_periods = (
            Period.objects.filter(is_active=True)
            .order_by("period_type", "date_start")
            .distinct("period_type")
        )
        return {period.period_type_id: period for period in actual_periods}


class OrgPreference(models.Model):
    """Параметр периодов оргструктур

    OrgPreference - Выбор названия таблицы обусловлен тем, что со временем в ней,
    возможно, будут храниться разные данные, а не только настройки текущего периода.
    Де факто - OrgPeriod
    """

    bus_unit_id = models.CharField("ID оргструктуры", max_length=50)
    period_type = models.ForeignKey(
        PeriodType,
        verbose_name="Тип периода",
        on_delete=models.PROTECT,
    )
    current_period = models.ForeignKey(
        Period, verbose_name="Период", on_delete=models.PROTECT
    )

    class Meta:
        app_label = "goal"

        verbose_name = "Настройка периодов оргструктур"
        verbose_name_plural = "Настройки периодов оргструктур"
        db_table = "org_preferences"
        unique_together = ("bus_unit_id", "period_type")

    def __str__(self):
        return f"{self.pk}: {self.bus_unit_id} - {self.current_period.period}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        self.clean_period_type()

    def clean_period_type(self):
        if self.period_type != self.current_period.period_type:
            raise ValidationError(
                f"Тип периода должен быть {self.current_period.period_type}"
            )
