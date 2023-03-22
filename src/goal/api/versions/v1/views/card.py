from django.db.models import Count, Max, Q
from django.http import FileResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.inspectors import SwaggerAutoSchema
from rest_framework.exceptions import APIException, MethodNotAllowed
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from src.goal.api.versions.v1.filters.backends import (
    PernumsFilterAdminBackend,
    PernumsFilterBackend,
)
from src.goal.api.versions.v1.filters.card import ProfileCardsFilter
from src.goal.api.versions.v1.permissions.card import (
    CardApproveForcePermission,
    CardApprovePermission,
    CardAssessmentApproveAdminPermission,
    CardAssessmentApproveMainPermission,
    CardDeclinePermission,
    CardManagerActionsPermission,
    CardPublishAdminViewPermission,
    CardPublishMainViewPermission,
    CardsStateViewPermission,
    CardStartPermission,
    CardsViewPermission,
    CardViewPermission,
    OrgstructureCardExportPermission,
    SingleCardStartPermission,
)
from src.goal.api.versions.v1.permissions.roles import SysAdminPermission
from src.goal.api.versions.v1.serializers.card import (
    CardApprovalHistorySerializer,
    CardCreateSerializer,
    CardProcedureStateSerializer,
    CardPublishSerializer,
    CardSerializer,
    CardSlimSerializer,
    CardsStageHistorySerializer,
    CardStatsSerializer,
    CardStatusHistorySerializer,
)
from src.goal.api.versions.v1.views._views import CollectionView, SingleObjectsView
from src.goal.integrations.hr.hr_edw import get_orgstructure
from src.goal.models import (
    Card,
    CardApprovalHistory,
    CardProcedureState,
    CardsAssessment,
    CardsStageHistory,
    CardStatusHistory,
    Notify,
    OrgStructureActionsLog,
    Period,
)
from src.goal.models.enums import ADMIN_ROLE
from src.goal.models.extensions.card_actions import (
    actions_state_update,
    actualize,
    approve_assessment,
)
from src.goal.models.extensions.card_actions import (
    approve_force_multiple as approve_force_cards,
)
from src.goal.models.extensions.card_actions import (
    assess,
    close_,
    export_by_id,
    export_by_orgstructure,
)
from src.goal.models.extensions.card_actions import (
    general_card_generation as generate_general_cards,
)
from src.goal.models.extensions.card_actions import (
    general_card_start,
    generate,
    interrupt_assessments,
    open_,
)
from src.goal.models.extensions.card_actions import start_many as start_cards
from src.goal.models.user import User
from src.goal.services.card_export.service import CardExportService, ExportCardFormat
from src.goal.tasks import (
    actualize_card,
    assess_card,
    close_card,
    interrupt_assessment,
    open_card,
    send_adm_assessment,
    send_assessment_approve,
    start_card_work,
)
from src.goal.tasks.camunda.card_agreement.send_approve_status import (
    send_approve_force_status,
    send_approve_status,
)
from src.goal.tasks.camunda.card_agreement.send_assessment_approve import (
    send_approve_assessment,
)
from src.helpers.decorators import swagger_fake_qs


class ActionsException(APIException):
    status_code = HTTP_400_BAD_REQUEST
    default_detail = "Ошибка смены статуса карты"


class CardsView(CollectionView):
    http_method_names = ["post", "options"]
    serializer_class = CardCreateSerializer
    permission_classes = (CardsViewPermission,)


class CardView(SingleObjectsView):
    serializer_class = CardSerializer
    permission_classes = (CardViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.objects.all()


class ProfileCardView(ListAPIView):
    swagger_schema = SwaggerAutoSchema
    filter_backends = (PernumsFilterBackend, DjangoFilterBackend)
    filterset_class = ProfileCardsFilter

    @swagger_fake_qs
    def get_queryset(self):
        return User(perno=int(self.kwargs["per_no"])).cards


class CardApproveView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardApprovePermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        try:
            send_approve_status(card, request.user.perno, True)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class CardApproveForceView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardApproveForcePermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_approved_force:
            raise ActionsException(detail=f"Карту {card.id} нельзя утвердить")
        try:
            send_approve_force_status(card.id)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class CardInterruptAssessmentView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardApproveForcePermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def retrieve(self, request, *args, **kwargs):
        card = self.get_object()
        if card.can_be_assessment_interrupted:
            interrupt_assessment(card)
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class CardApproveAssessmentView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardApproveForcePermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_assessment_approved:
            raise ActionsException(detail=f"Оценку карты {card.id} нельзя утвердить")
        try:
            send_approve_assessment(card)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class CardDeclineView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardDeclinePermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        try:
            send_approve_status(card, request.user.perno, False)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class OrgstructureCardsStartView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.objects_can_be_started.all()

    def retrieve(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = bool(
            request.query_params.get("with_hierarchy", "false").lower() == "true"
        )
        period = Period.objects.get(id=period_id)

        if with_hierarchy:
            unit_list = get_orgstructure(
                url_params={
                    "unit": bus_unit_id,
                    "fields": "flat_list_subunits",
                    "interval_start": period.date_start.isoformat(),
                    "interval_end": period.date_end.isoformat(),
                }
            )

            cards = self.get_queryset().filter(
                business_unit__in=unit_list[0]["flat_list_subunits"]
                if unit_list
                else [bus_unit_id],
                period_id=period_id,
            )
        else:
            cards = self.get_queryset().filter(
                business_unit=bus_unit_id,
                period_id=period_id,
            )

        start_cards(
            cards, self.request.user.perno, bus_unit_id, with_hierarchy=with_hierarchy
        )

        serializer = self.get_serializer(cards, many=True)
        return Response(serializer.data)


class OrgstructureCardsExportView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (OrgstructureCardExportPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.objects.all()

    @staticmethod
    def get_flags(request) -> dict:
        params = ("curr_bus_unit", "with_subunits", "goals", "mail_sending", "result")
        return {
            param: request.query_params.get(param, "false").lower() == "true"
            for param in params
        }

    def retrieve(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")

        flags = self.get_flags(request)

        if flags.get("mail_sending"):
            export_by_orgstructure(
                user_perno=request.user.perno,
                user_email=request.user.email,
                is_user_admin=request.user.is_sys_admin,
                unit=bus_unit_id,
                period_id=period_id,
                flags=flags,
            )
            return Response(
                f"Запущена генерация отчета КПЭ для подразделения: {bus_unit_id}"
            )

        export_service = CardExportService(
            export_format=ExportCardFormat.XLSX,
            notify_user_perno=request.user.perno,
            is_notify_user_admin=request.user.is_sys_admin,
            flags=flags,
            receiver_key=request.user.perno,
        )
        export_service.prepare_service_for_bulk_export(
            business_unit=bus_unit_id,
            period_id=period_id,
        )
        for index, card in enumerate(export_service.cards, start=1):
            export_service.target_strategy.process_card(index, card)
        file, filename = export_service.export()

        return FileResponse(file, filename=filename, as_attachment=True)


class CardGenerateView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardManagerActionsPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = request.query_params.get("with_hierarchy", "false")
        with_hierarchy = bool(with_hierarchy.lower() == "true")
        action_log = OrgStructureActionsLog.objects.create(
            action_type=OrgStructureActionsLog.GENERATE,
            initiator_perno=self.request.user.perno,
            business_unit=bus_unit_id,
            with_hierarchy=with_hierarchy,
        )
        generate(
            bus_unit_id,
            period_id,
            self.request.user,
            with_hierarchy=with_hierarchy,
            action_log=action_log.id,
        )
        message = f"Запущены задачи генерации карт для подразделения {bus_unit_id}"
        if with_hierarchy:
            message += " и вложенных."
        return Response(message)


class CardActualizeView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardManagerActionsPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = request.query_params.get("with_hierarchy", "false")
        with_hierarchy = with_hierarchy.lower() == "true"
        actualize(bus_unit_id, period_id, self.request.user, with_hierarchy)
        if with_hierarchy:
            return Response(
                f"Запущены задачи актуализации карт для подразделения {bus_unit_id} и "
                f"вложенных."
            )
        return Response(f"Запущена актуализация для подразделения: {bus_unit_id}")


class CardAssessView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardManagerActionsPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = request.query_params.get("with_hierarchy", "false")
        with_hierarchy = with_hierarchy.lower() == "true"
        assess(bus_unit_id, period_id, self.request.user, with_hierarchy)
        if with_hierarchy:
            return Response(
                f"Запущены задачи обновления состояния оценки карт для подразделения "
                f"{bus_unit_id} и вложенных."
            )
        return Response(
            f"Запущено обновление состояния оценки карт "
            f"для подразделения: {bus_unit_id}"
        )


class CardCloseView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardManagerActionsPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = request.query_params.get("with_hierarchy", "false")
        with_hierarchy = with_hierarchy.lower() == "true"
        close_(bus_unit_id, period_id, self.request.user, with_hierarchy)
        if with_hierarchy:
            return Response(
                f"Запущено закрытие карт для подразделения {bus_unit_id} и вложенных."
            )
        return Response(f"Запущено закрытие карт для подразделения: {bus_unit_id}")


class CardOpenView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardManagerActionsPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = request.query_params.get("with_hierarchy", "false")
        with_hierarchy = with_hierarchy.lower() == "true"
        open_(bus_unit_id, period_id, self.request.user, with_hierarchy)
        if with_hierarchy:
            return Response(
                f"Запущено открытие карт для подразделения {bus_unit_id} и вложенных."
            )
        return Response(f"Запущено открытие карт для подразделения: {bus_unit_id}")


class CardExportView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.objects.all()

    @classmethod
    def get_flags(cls, request):
        params = ("curr_bus_unit", "with_subunits", "goals", "mail_sending", "result")
        return {
            param: request.query_params.get(param, "false").lower() == "true"
            for param in params
        }

    def retrieve(self, request, *args, **kwargs):
        card = self.get_object()
        flags = self.get_flags(request)

        if flags.get("mail_sending"):
            export_by_id(
                card_id=card.pk,
                user_perno=request.user.perno,
                user_email=request.user.email,
                is_user_admin=request.user.is_sys_admin,
                flags=flags,
            )
            return Response(
                f"Запущена генерация отчета КПЭ для сотрудника {request.user.perno}"
            )

        export_service = CardExportService(
            ExportCardFormat.XLSX,
            flags=flags,
            notify_user_perno=request.user.perno,
            is_notify_user_admin=request.user.is_sys_admin,
            notify_message=f"Экспортирована карта сотрудника {request.user.perno}.",
            receiver_key=request.user.perno,
        )
        export_service.cards = ((card,),)
        file, filename = export_service.export()

        return FileResponse(file, filename=filename, as_attachment=True)


class CardStatusHistoryView(ListAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardStatusHistorySerializer
    permission_classes = (CardViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return CardStatusHistory.objects.filter(card=self.kwargs["card_id"])


class CardApprovalHistoryView(ListAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardApprovalHistorySerializer
    permission_classes = (CardViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return CardApprovalHistory.objects.filter(card=self.kwargs["card_id"])


class CardsStageHistoryView(ListAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardsStageHistorySerializer
    permission_classes = (CardViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return CardsStageHistory.objects.filter(card=self.kwargs["card_id"])


class CardStageView(APIView):
    swagger_schema = SwaggerAutoSchema

    @swagger_fake_qs
    def get_queryset(self):
        return CardsStageHistory.objects.filter(card=self.kwargs["card_id"])

    def get(self, request, *args, **kwargs):
        stages = {
            Card.ON_SETTING.key: CardsStageHistory.NOT_STARTED,
            Card.ON_ACTUALIZATION.key: CardsStageHistory.NOT_STARTED,
            Card.ON_ASSESSMENT.key: CardsStageHistory.NOT_STARTED,
        }
        last_ids_in_history = (
            self.get_queryset()
            .values("stage")
            .annotate(id=Max("id"))
            .values_list("id", flat=True)
        )
        qs = CardsStageHistory.objects.filter(id__in=last_ids_in_history).order_by("id")
        for card_history in qs:
            # карта может вернуться назад, сбрасываем следующие этапы
            if card_history.stage == Card.ON_SETTING.key:
                stages[Card.ON_ACTUALIZATION.key] = CardsStageHistory.NOT_STARTED
                stages[Card.ON_ASSESSMENT.key] = CardsStageHistory.NOT_STARTED
            if card_history.stage == Card.ON_ACTUALIZATION.key:
                stages[Card.ON_ASSESSMENT.key] = CardsStageHistory.NOT_STARTED

            if card_history.end_dt:
                stages[card_history.stage] = CardsStageHistory.SUCCESS
                continue
            stages[card_history.stage] = CardsStageHistory.IN_PROGRESS
        return Response(stages)


class CardProcedureStateView(RetrieveUpdateAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardProcedureStateSerializer
    permission_classes = (CardsStateViewPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return CardProcedureState.objects.all()

    def get_object(self):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        state = CardProcedureState.objects.filter(
            period_id=period_id, business_unit=bus_unit_id
        ).first()
        return state

    def put(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        data = request.data
        generation_with_hierarchy = bool(data.get("generation_with_hierarchy"))
        start_with_hierarchy = bool(data.get("start_with_hierarchy"))

        if generation_with_hierarchy or start_with_hierarchy:
            actions_state_update(bus_unit_id, period_id, self.request.user, data)
            return Response(
                f"Запущено обновление состояний автогенерации для подразделения {bus_unit_id} и вложенных",
                status=HTTP_200_OK,
            )

        bus_unit = get_orgstructure(
            url_params={
                "unit": bus_unit_id,
                "fields": "organizational_unit_desc,name",
            }
        )[0]

        bus_unit_name = max(
            bus_unit.get("organizational_unit_desc") or "",
            bus_unit.get("name") or "",
        )

        state, created = CardProcedureState.objects.get_or_create(
            period_id=period_id, business_unit=bus_unit_id
        )

        if "enable_generation" in data:
            state.is_generation_enabled = data["enable_generation"]
            Notify.objects.create(
                perno=self.request.user.perno,
                type=ADMIN_ROLE,
                message=f"Для орг. единицы {bus_unit_name} ({bus_unit_id}) обновлено состояние генерации",
            )
        if "enable_start" in data:
            state.is_start_enabled = data["enable_start"]
            Notify.objects.create(
                perno=self.request.user.perno,
                type=ADMIN_ROLE,
                message=f"Для орг. единицы {bus_unit_name} ({bus_unit_id}) обновлено состояние назначения",
            )
        state.save()

        return Response(
            f"Обновлено состояние автогенерации для подразделения {bus_unit_id}"
        )

    def patch(self, request, *args, **kwargs):
        raise MethodNotAllowed("PATCH")


class CardStateGenerateView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (SysAdminPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.request.query_params.get("period_id")
        generate_general_cards(self.request.user, period_id)
        return Response("Запущена генерация для подразделений из настроек")


class CardStateStartView(APIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (SysAdminPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.request.query_params.get("period_id")
        general_card_start(self.request.user, period_id)
        return Response("Запущено назначение карт для подразделений из настроек")


class SingleCardStartView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (SingleCardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.objects.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_started:
            raise ActionsException(detail=f"Карту {card.id} нельзя назначить")
        try:
            start_card_work(card.id)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class OrgstructureCardsApproveForceView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def retrieve(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = bool(
            request.query_params.get("with_hierarchy", "false").lower() == "true"
        )
        approve_force_cards(bus_unit_id, period_id, self.request.user, with_hierarchy)

        return Response("Запущен процесс утверждения карт")


class OrgstructureCardsInterruptAssessmentView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (CardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def retrieve(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = bool(
            request.query_params.get("with_hierarchy", "false").lower() == "true"
        )
        interrupt_assessments(bus_unit_id, period_id, self.request.user, with_hierarchy)

        return Response("Запущен процесс сброса оценок карт")


class OrgstructureCardsApproveAssessmentView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardStartPermission,)

    def get(self, request, *args, **kwargs):
        period_id = self.kwargs.get("period_id")
        bus_unit_id = self.kwargs.get("bus_unit_id")
        with_hierarchy = bool(
            request.query_params.get("with_hierarchy", "false").lower() == "true"
        )
        approve_assessment(bus_unit_id, period_id, self.request.user, with_hierarchy)

        return Response("Запущен процесс утверждения оценок карт")


class CardPublishMainView(SingleObjectsView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardPublishSerializer
    permission_classes = (CardPublishMainViewPermission,)
    lookup_field = "card_id"

    http_method_names = ["options", "patch"]

    @swagger_fake_qs
    def get_queryset(self):
        return CardsAssessment.objects.prefetch_related(
            "individual_matrix_value", "card"
        ).all()

    def patch(self, request, *args, **kwargs):
        card_assessment = self.get_object()
        serializer = self.get_serializer(instance=card_assessment, data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            send_adm_assessment(
                card_assessment,
                serializer.validated_data.get("personnel_kpi_done_percent"),
            )
            return Response("Запущен процесс публикации карты")
        except Exception as e:
            return Response(f"Ошибка публикации карты. Причина: {e}", status=422)


class CardPublishAdminView(CardPublishMainView):
    permission_classes = (CardPublishAdminViewPermission,)


class CardAssessmentApproveMainView(SingleObjectsView):
    swagger_schema = SwaggerAutoSchema
    permission_classes = (CardAssessmentApproveMainPermission,)
    http_method_names = ["options", "patch"]

    def get_queryset(self):
        return Card.objects.all()

    def patch(self, request, *args, **kwargs):
        approved = request.data.get("approved")
        if not isinstance(approved, bool):
            return Response(
                status=HTTP_400_BAD_REQUEST, data='Invalid "approved" parameter'
            )
        try:
            send_assessment_approve(self.get_object(), approved)
            return Response(
                "Запущен процесс согласования выполнения индивидуальных КПЭ"
            )
        except Exception as e:
            return Response(
                f"Процесс согласования выполнения индивидуальных КПЭ не запущен. Причина: {e}",
                status=422,
            )


class CardAssessmentApproveAdminView(CardAssessmentApproveMainView):
    permission_classes = (CardAssessmentApproveAdminPermission,)


class SingleCardActualizeView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (SingleCardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_actualized:
            raise ActionsException(detail=f"Карту {card.id} нельзя актуализировать")
        try:
            actualize_card(card)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class SingleCardAssessView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (SingleCardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_assessed:
            raise ActionsException(detail=f"Карте {card.id} нельзя назначить оценку")
        try:
            assess_card(card)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class SingleCardCloseView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (SingleCardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_closed:
            raise ActionsException(detail=f"Карту {card.id} нельзя закрыть")
        try:
            close_card(card)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class SingleCardOpenView(GenericAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardSlimSerializer
    permission_classes = (SingleCardStartPermission,)

    @swagger_fake_qs
    def get_queryset(self):
        return Card.actual.all()

    def get(self, request, *args, **kwargs):
        card = self.get_object()
        if not card.can_be_opened:
            raise ActionsException(detail=f"Карту {card.id} нельзя открыть")
        try:
            open_card(card)
        except Exception as e:
            raise ActionsException(detail=str(e))
        serializer = self.get_serializer(card)
        return Response(serializer.data)


class CardStatsView(RetrieveAPIView):
    swagger_schema = SwaggerAutoSchema
    serializer_class = CardStatsSerializer
    filter_backends = (PernumsFilterAdminBackend,)

    @swagger_fake_qs
    def get_queryset(self):
        qs = self.filter_queryset(User(perno=int(self.kwargs["per_no"])).cards)
        qs = qs.aggregate(
            total=Count("pk"),
            with_active_period=Count("pk", filter=Q(period__is_active=True)),
            with_active_state=Count("pk", filter=Q(state=Card.ACTIVE.key)),
            actual=Count(
                "pk",
                filter=Q(
                    state__in=[Card.ACTIVE.key, Card.CLOSED.key], period__is_active=True
                ),
            ),
        )
        return qs

    def retrieve(self, request, *args, **kwargs):
        stats = self.get_queryset()
        serializer = self.get_serializer(stats)
        return Response(serializer.data)
