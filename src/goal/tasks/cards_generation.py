import logging

from django.apps import apps
from django.db.models import F

from src.celery import LogErrorsTask, app
from src.goal.api.versions.v1.permissions._helpers import (
    has_goal_admin_permissions_unit_by_perno,
)
from src.goal.integrations.hr.hr_edw import (
    get_employees_by_orgstructure,
    get_orgstructure,
)
from src.goal.models import OrgStructureActionsLog
from src.goal.models.card import CardProcedureState
from src.goal.services.card_generation.consts import CardActivity
from src.goal.services.card_generation.service import CardGenerationService
from src.goal.tasks.camunda.card_agreement._helpers import (
    create_notify,
    get_organization_name,
)
from src.helpers.decorators import retry


logger = logging.getLogger(__name__)


def _generate_cards_for_unit(bus_unit_id, period_id, task_id, action_log=None):

    Period = apps.get_model("goal.Period")
    period = Period.objects.get(id=period_id)
    all_suited_employees = get_employees_by_orgstructure(
        bus_unit_id,
        period,
        list(period.bonus_types.values_list("key", flat=True).all()),
    )
    generation_service = CardGenerationService(period, task_id)

    for employee in all_suited_employees:
        generation_service.generate_cards_for_employee(employee)

    created, updated, reactivated, checked, errors = (
        generation_service.results[CardActivity.created.value],
        generation_service.results[CardActivity.updated.value],
        generation_service.results[CardActivity.reactivated.value],
        generation_service.results[CardActivity.checked.value],
        generation_service.results[CardActivity.errors.value],
    )
    personal_deactivate_count = (
        generation_service.employee_deactivate_manager.deactivated_cards_counter
    )
    personal_deactivate_errors_count = (
        generation_service.employee_deactivate_manager.deactivation_errors_counter
    )

    card_ids = generation_service.unit_deactivate_manager.unpack_card_ids(
        [*generation_service.employee_cards.values()]
    )
    generation_service.unit_deactivate_manager.check_cards_for_deactivation(
        card_ids, bus_unit_id
    )

    deactivate_count = (
        personal_deactivate_count
        + generation_service.unit_deactivate_manager.deactivated_cards_counter
    )

    deactivate_errors = (
        personal_deactivate_errors_count
        + generation_service.unit_deactivate_manager.deactivation_errors_counter
    )
    errors += deactivate_errors
    if action_log and any(
        [
            created,
            updated,
            reactivated,
            deactivate_count,
            errors,
        ]
    ):
        OrgStructureActionsLog.objects.filter(id=action_log).update(
            created_count=F("created_count") + created,
            updated_count=F("updated_count") + updated,
            deactivated_count=F("deactivated_count") + deactivate_count,
            reactivated_count=F("reactivated_count") + reactivated,
            errors=F("errors") + errors,
        )
    logger.info(
        f"Оргструктура {bus_unit_id}. Создано карт: {created}, "
        f"обновлено карт: {updated}, "
        f"деактивировано карт: {deactivate_count}, "
        f"ре-активировано карт: {reactivated}, "
        f"ошибок: {errors}, "
        f"проверено {checked}"
    )
    return {
        "created": created,
        "updated": updated,
        "checked": checked,
        "reactivated": reactivated,
        "errors": errors,
        "deactivated": deactivate_count,
    }


@app.task(name="camunda.agreement.generate_cards", base=LogErrorsTask)
def generate_cards(
    bus_unit_id,
    period_id,
    user_perno,
    task_id,
    action_log=None,
    is_user_sysadmin=False,
    with_hierarchy=True,
):
    Period = apps.get_model("goal.Period")
    period = Period.objects.get(id=period_id)
    units_list = (bus_unit_id,)
    if with_hierarchy:
        unit_list_response = get_orgstructure(
            url_params={
                "unit": bus_unit_id,
                "fields": "flat_list_subunits",
                "interval_start": period.date_start.isoformat(),
                "interval_end": period.date_end.isoformat(),
            }
        )

        if len(unit_list_response) > 0:
            units_list = unit_list_response[0].get("flat_list_subunits", tuple())

    total_counts = {
        "created": 0,
        "updated": 0,
        "checked": 0,
        "errors": 0,
        "deactivated": 0,
        "reactivated": 0,
        "units": 0,
    }
    error_list = []
    progress_message = (
        f"Запущена генерация в {period.period} периоде для подразделения {bus_unit_id}"
    )
    if with_hierarchy:
        progress_message += " и его вложенных подразделений"
    notify = create_notify(user_perno, progress_message)
    done_percent = 0
    for index, unit_id in enumerate(units_list):
        if is_user_sysadmin or has_goal_admin_permissions_unit_by_perno(
            unit_id, user_perno
        ):
            try:
                counts = generate_cards_for_unit(
                    bus_unit_id=unit_id,
                    period_id=period_id,
                    task_id=task_id,
                    action_log=action_log,
                )
                for key, value in counts.items():
                    total_counts[key] = total_counts.get(key, 0) + value
                total_counts["units"] += 1

                if counts.get("errors", 0) > 0:
                    error_list.append(
                        f"Ошибка при генерации карт для подразделения {unit_id} "
                        f"({counts['errors']} шт)"
                    )
            except:
                logger.error(f"Ошибка при генерации карт для подразделения {unit_id}")
        if with_hierarchy:
            # При генерации для всей иерархии, обновляем статус прогресса
            curr_percent = int((index + 1) / len(units_list) * 100)
            if curr_percent > done_percent:
                done_percent = curr_percent
                notify.message = (
                    progress_message
                    + "\nОбработано подразделений: "
                    + f"{index + 1}/{len(units_list)} ({done_percent}%)"
                )
                notify.is_new = True
                notify.save(update_fields=["message", "date_created", "is_new"])

    # notify
    bus_unit_name = get_organization_name(bus_unit_id)
    subunits_count = (
        f" c учетом вложенных {total_counts['units']} подразделений"
        if with_hierarchy
        else ""
    )
    message = f"""Для орг. единицы "{bus_unit_name}" ({bus_unit_id}) {subunits_count}
    - Создано: {total_counts['created']} карт
    - Обновлено: {total_counts['updated']} карт
    - Деактивировано (удалено): {total_counts['deactivated']} карт
    - Активировано заново: {total_counts['reactivated']} карт
    - Проверено: {total_counts['checked']} карт
    - Ошибок: {total_counts['errors']}"""
    if error_list:
        message += "\n\nОшибки:\n" + "\n".join(error_list[:10])
    create_notify(user_perno, message)


@retry(max_retry=5, backoff=1, retry_on_exceptions=(Exception,))
def generate_cards_for_unit(bus_unit_id, period_id, task_id, action_log=None):
    return _generate_cards_for_unit(
        bus_unit_id, period_id, task_id, action_log=action_log
    )


@app.task(name="camunda.agreement.generate_cards_from_state", base=LogErrorsTask)
def generate_cards_from_state(user_perno, period_id, task_id):
    states = CardProcedureState.objects.filter(
        is_generation_enabled=True, period_id=period_id
    )
    Period = apps.get_model("goal.Period")
    period = Period.objects.get(id=period_id)
    total_counts = {
        "created": 0,
        "updated": 0,
        "checked": 0,
        "errors": 0,
        "deactivated": 0,
        "units": 0,
    }
    for state in states:
        counts = generate_cards_for_unit(
            bus_unit_id=state.business_unit,
            period_id=state.period_id,
            task_id=task_id,
        )
        for key, value in counts.items():
            total_counts[key] = total_counts.get(key, 0) + value
        total_counts["units"] += 1
    create_notify(
        user_perno,
        f"""В результате ручного запуска генерации карт в {period.period} периоде для {total_counts['units']} подразделений:
    - Создано: {total_counts['created']} карт
    - Обновлено: {total_counts['updated']} карт
    - Деактивировано (удалено): {total_counts['deactivated']} карт
    - Проверено: {total_counts['checked']} карт
    - Ошибок: {total_counts['errors']}""",
    )
