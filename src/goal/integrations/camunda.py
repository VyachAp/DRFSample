import base64
import logging
import os
import uuid
from typing import Any, Dict, Optional

import requests
from django.conf import settings

from src.helpers.exceptions.camunda import NoTask


logger = logging.getLogger(__name__)


def set_variable(variable: Any) -> dict:
    return {"value": variable}


def get_worker_id():
    return str(uuid.uuid4())


def make_request(method: str, url: str, **kwargs) -> Optional[dict]:
    """
    Общий метод для запросов в Camunda
    docs: https://docs.camunda.org/manual/7.7/reference/rest/
    :param method:
    :param url:
    :param kwargs:
    :return: dict or None
    """
    url = url.lstrip("/")
    url = f"{settings.CAMUNDA_URL}/engine-rest/{url}"
    auth_header = os.getenv("CAMUNDA_LOGINPASSWORD_BASE64", None)
    if not auth_header:
        raise Exception("No auth header provided for camunda")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {base64.b64encode(str(auth_header).encode()).decode('ascii')}",
    }
    response = requests.request(
        method=method, url=url, headers=headers, timeout=5, **kwargs
    )
    if 200 <= response.status_code < 300:
        if response.content:
            return response.json()
        return
    raise Exception(f"Camunda error: {response.status_code} | {response.content}")


def get_task(topic: str, worker_id: Any, variables: list = None) -> Dict:
    """
    Метод для получения задачи за закрепления ее за конкретным воркером
    docs: https://docs.camunda.org/manual/7.7/reference/rest/external-task/fetch/
    :param topic:
    :param worker_id:
    :param variables:
    :return: List - список задач
    """
    data = {
        "workerId": worker_id,
        "maxTasks": settings.CAMUNDA_TASK_BATCH,
        "usePriority": True,
        "topics": [{"topicName": topic, "lockDuration": 30000}],
    }
    if variables:
        data["topics"][0].update({"variables": variables})
    tasks = make_request(method="post", url="external-task/fetchAndLock", json=data)
    if tasks:
        return tasks
    raise NoTask


def finish_task(task_id: str, worker_id: Any, variables: dict = None) -> None:
    """
    Метод для завершения задачи
    docs: https://docs.camunda.org/manual/7.7/reference/rest/external-task/post-complete/
    :param task_id:
    :param worker_id:
    :param variables:
    :return: None
    """
    data = {
        "workerId": worker_id,
    }
    if variables:
        data.update({"variables": variables})
    make_request(method="post", url=f"external-task/{task_id}/complete", json=data)


def start_process(business_key: str, process_id: str, variables: dict = None) -> Dict:
    """
    Метод для запуска инстанса процесса
    docs: https://docs.camunda.org/manual/7.7/reference/rest/process-definition/post-start-process-instance/
    :param business_key:
    :param process_id:
    :param variables:
    :return: None
    """
    data = {"businessKey": business_key}
    if variables:
        data.update({"variables": variables})
    return make_request(
        method="post", url=f"process-definition/key/{process_id}/start", json=data
    )


def send_message(business_key: str, message_name: str, variables: dict = None) -> None:
    """
    Метод для отправки сообщения в Camunda
    docs: https://docs.camunda.org/manual/latest/reference/rest/message/post-message/
    :param business_key:
    :param message_name:
    :param variables:
    :return: None
    """
    data = {
        "messageName": message_name,
        "businessKey": business_key,
    }
    if variables:
        data.update({"processVariables": variables})
    make_request(method="post", url="message", json=data)
