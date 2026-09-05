# -*- coding: utf-8 -*-
"""Alexa skill: Menú de Ada

Reads Ada's school lunch from Skolmat.info and answers in Spanish.
The food names are returned exactly as published by the school.
"""

import json
import logging
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Identifier taken from the RSS URL supplied by the user:
# https://www.skolmat.info/api/public/matsedlar/<THIS_ID>/rss?limit=7
FACILITY_ID = "cmruev9zs000z04jm7oqrub01"
API_BASE = f"https://www.skolmat.info/api/public/matsedlar/{FACILITY_ID}"
TIMEZONE = ZoneInfo("Europe/Stockholm")

DAY_KEYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)

WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)

MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# Warm-Lambda cache. It avoids hitting Skolmat repeatedly when several questions
# arrive close together. Cache lifetime is intentionally short so menu edits show up.
_WEEK_CACHE = {}
CACHE_SECONDS = 15 * 60


def stockholm_today() -> date:
    return datetime.now(TIMEZONE).date()


def _fetch_week(year: int, week: int) -> dict:
    key = (year, week)
    now = time.time()
    cached = _WEEK_CACHE.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

    url = f"{API_BASE}?{urlencode({'year': year, 'week': week})}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Referer": "https://www.skolmat.info/",
            "User-Agent": "AdaSchoolLunchAlexa/1.0",
        },
    )

    with urlopen(request, timeout=4) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("Skolmat returned an unsuccessful response")

    week_data = payload.get("week")
    if not isinstance(week_data, dict):
        raise ValueError("Skolmat response does not contain week data")

    _WEEK_CACHE[key] = (now, week_data)
    return week_data


def _extract_dishes(week_data: dict, target_date: date) -> list[str]:
    """Extract non-empty, de-duplicated dish text for target_date."""
    day_key = DAY_KEYS[target_date.isoweekday() - 1]
    days = week_data.get("days", {})
    day_data = days.get(day_key)

    if not isinstance(day_data, dict) or not day_data.get("isOpen"):
        return []

    dishes = []
    seen = set()
    for row in day_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get("text", "")).split()).strip()
        if text and text.casefold() not in seen:
            dishes.append(text)
            seen.add(text.casefold())

    return dishes


def get_menu(target_date: date) -> list[str]:
    iso_year, iso_week, _ = target_date.isocalendar()
    week_data = _fetch_week(iso_year, iso_week)
    return _extract_dishes(week_data, target_date)


def join_spanish(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} y {items[1]}"
    return f"{', '.join(items[:-1])} y {items[-1]}"


def date_phrase(target: date, today: date) -> str:
    if target == today:
        return "Hoy"
    if target == today + timedelta(days=1):
        return "Mañana"
    return (
        f"El {WEEKDAYS_ES[target.weekday()]} {target.day} "
        f"de {MONTHS_ES[target.month - 1]}"
    )


def menu_answer(target_date: date) -> tuple[str, str]:
    """Return (speech, card_text)."""
    today = stockholm_today()
    dishes = get_menu(target_date)
    when = date_phrase(target_date, today)

    if not dishes:
        speech = f"{when} no hay ningún menú publicado para el colegio."
        return speech, speech

    menu = join_spanish(dishes)
    speech = f"{when}, en el colegio hay {menu}."
    card = f"{when}:\n" + "\n".join(f"• {dish}" for dish in dishes)
    return speech, card


def parse_alexa_date(value: str | None) -> date | None:
    """Accept the full YYYY-MM-DD values AMAZON.DATE returns for specific dates."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def response_with_menu(handler_input: HandlerInput, target_date: date) -> Response:
    speech, card = menu_answer(target_date)
    handler_input.response_builder.speak(speech).set_card(SimpleCard("Menú de Ada", card))
    return handler_input.response_builder.response


class LaunchRequestHandler(AbstractRequestHandler):
    """'Alexa, abre menú de Ada' immediately returns today's lunch."""

    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        return response_with_menu(handler_input, stockholm_today())


class MenuForDateIntentHandler(AbstractRequestHandler):
    """Questions such as 'qué hay mañana para comer' or 'qué hay el lunes'."""

    def can_handle(self, handler_input):
        return is_intent_name("MenuForDateIntent")(handler_input)

    def handle(self, handler_input):
        raw_date = get_slot_value(handler_input, slot_name="fecha")
        target = parse_alexa_date(raw_date)
        if target is None:
            speech = "Dime un día concreto, por ejemplo hoy, mañana o el lunes."
            handler_input.response_builder.speak(speech).ask(speech)
            return handler_input.response_builder.response
        return response_with_menu(handler_input, target)


class NextSchoolMenuIntentHandler(AbstractRequestHandler):
    """Find the next day for which Skolmat actually publishes food."""

    def can_handle(self, handler_input):
        return is_intent_name("NextSchoolMenuIntent")(handler_input)

    def handle(self, handler_input):
        start = stockholm_today()
        for offset in range(0, 11):
            candidate = start + timedelta(days=offset)
            dishes = get_menu(candidate)
            if dishes:
                speech, card = menu_answer(candidate)
                handler_input.response_builder.speak(speech).set_card(
                    SimpleCard("Menú de Ada", card)
                )
                return handler_input.response_builder.response

        speech = "No encuentro ningún menú publicado para los próximos días."
        handler_input.response_builder.speak(speech)
        return handler_input.response_builder.response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speech = (
            "Puedes preguntarme qué hay hoy para comer, qué hay mañana, "
            "qué hay el lunes, o cuál es el próximo menú."
        )
        handler_input.response_builder.speak(speech).ask(
            "Por ejemplo, pregunta qué hay mañana para comer."
        )
        return handler_input.response_builder.response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            is_intent_name("AMAZON.CancelIntent")(handler_input)
            or is_intent_name("AMAZON.StopIntent")(handler_input)
        )

    def handle(self, handler_input):
        handler_input.response_builder.speak("Hasta luego.")
        return handler_input.response_builder.response


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        speech = "No he entendido el día. Puedes decir hoy, mañana o el lunes."
        handler_input.response_builder.speak(speech).ask(speech)
        return handler_input.response_builder.response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.exception("Unhandled error in Menú de Ada", exc_info=exception)
        speech = (
            "No he podido consultar el menú de Skolmat ahora mismo. "
            "Inténtalo de nuevo dentro de un momento."
        )
        handler_input.response_builder.speak(speech)
        return handler_input.response_builder.response


sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(MenuForDateIntentHandler())
sb.add_request_handler(NextSchoolMenuIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
