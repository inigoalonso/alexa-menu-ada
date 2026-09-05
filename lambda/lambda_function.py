# -*- coding: utf-8 -*-
"""Alexa skill: Menú de Ada

Python 3.8 compatible.
Primary source: Skolmat JSON endpoint.
Fallback source: the RSS feed supplied by the user.
"""

import html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pytz
from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FACILITY_ID = "cmruev9zs000z04jm7oqrub01"
API_BASE = "https://www.skolmat.info/api/public/matsedlar/{0}".format(FACILITY_ID)
RSS_URL = API_BASE + "/rss?limit=14"
TIMEZONE = pytz.timezone("Europe/Stockholm")

DAY_KEYS = (
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
    "FRIDAY", "SATURDAY", "SUNDAY"
)

WEEKDAYS_ES = (
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo"
)

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
)

SWEDISH_WEEKDAYS = {
    "måndag": 0, "mandag": 0,
    "tisdag": 1,
    "onsdag": 2,
    "torsdag": 3,
    "fredag": 4,
    "lördag": 5, "lordag": 5,
    "söndag": 6, "sondag": 6,
}

SWEDISH_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4,
    "maj": 5, "juni": 6, "juli": 7, "augusti": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}

_WEEK_CACHE = {}
CACHE_SECONDS = 15 * 60


def stockholm_today():
    return datetime.now(TIMEZONE).date()


def _http_get(url, accept):
    request = Request(
        url,
        headers={
            "Accept": accept,
            "Referer": "https://www.skolmat.info/",
            "User-Agent": "AdaSchoolLunchAlexa/2.0",
        },
    )
    with urlopen(request, timeout=6) as response:
        return response.read()


def _fetch_week_json(year, week):
    key = (year, week)
    now = time.time()
    cached = _WEEK_CACHE.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

    url = "{0}?{1}".format(API_BASE, urlencode({"year": year, "week": week}))
    payload = json.loads(_http_get(url, "application/json").decode("utf-8"))

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("Skolmat JSON response was not successful")

    week_data = payload.get("week")
    if not isinstance(week_data, dict):
        raise ValueError("Skolmat JSON response has no week object")

    _WEEK_CACHE[key] = (now, week_data)
    return week_data


def _extract_dishes_json(week_data, target_date):
    day_key = DAY_KEYS[target_date.isoweekday() - 1]
    days = week_data.get("days", {})
    day_data = days.get(day_key)

    if not isinstance(day_data, dict):
        return []
    if day_data.get("isOpen") is False:
        return []

    dishes = []
    seen = set()
    for row in day_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get("text", "")).split()).strip()
        folded = text.casefold()
        if text and folded not in seen:
            dishes.append(text)
            seen.add(folded)
    return dishes


def _clean_rss_description(value):
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    lines = []
    for part in value.splitlines():
        part = " ".join(part.split()).strip(" -•\t")
        if part:
            lines.append(part)
    if lines:
        return " | ".join(lines)
    return " ".join(value.split()).strip()


def _rss_item_date(item, reference_date):
    # 1. Standard RSS pubDate, if it actually represents the menu date.
    pub_date = item.findtext("pubDate")
    if pub_date:
        try:
            dt = parsedate_to_datetime(pub_date)
            if dt is not None:
                candidate = dt.date()
                # Only trust it when reasonably close to the requested period.
                if abs((candidate - reference_date).days) <= 21:
                    return candidate
        except Exception:
            pass

    title = (item.findtext("title") or "").strip()
    lowered = title.casefold()

    # 2. Explicit YYYY-MM-DD somewhere in the title.
    match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", title)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    # 3. Swedish '7 september' style title. Infer year near reference date.
    month_num = None
    for month_name, number in SWEDISH_MONTHS.items():
        if month_name in lowered:
            month_num = number
            break
    if month_num:
        day_match = re.search(r"\b([0-3]?\d)\b", lowered)
        if day_match:
            day_num = int(day_match.group(1))
            candidates = []
            for year in (reference_date.year - 1, reference_date.year, reference_date.year + 1):
                try:
                    candidates.append(date(year, month_num, day_num))
                except ValueError:
                    pass
            if candidates:
                return min(candidates, key=lambda d: abs((d - reference_date).days))

    # 4. Weekday-only title. Pick the matching weekday nearest the reference date.
    for weekday_name, weekday_num in SWEDISH_WEEKDAYS.items():
        if weekday_name in lowered:
            delta = weekday_num - reference_date.weekday()
            return reference_date + timedelta(days=delta)

    return None


def _fetch_rss_entries(reference_date):
    raw = _http_get(RSS_URL, "application/rss+xml, application/xml, text/xml")
    root = ET.fromstring(raw)
    entries = []
    for item in root.findall(".//item"):
        item_date = _rss_item_date(item, reference_date)
        description = _clean_rss_description(item.findtext("description") or "")
        if item_date and description:
            entries.append((item_date, description))
    return entries


def _rss_dishes_for_date(target_date):
    entries = _fetch_rss_entries(target_date)
    for item_date, description in entries:
        if item_date == target_date:
            # Keep RSS description as one spoken item. It often already contains
            # multiple courses separated cleanly by punctuation or line breaks.
            return [description]
    return []


def get_menu(target_date):
    # Primary path: structured JSON.
    try:
        iso_year, iso_week, _ = target_date.isocalendar()
        week_data = _fetch_week_json(iso_year, iso_week)
        dishes = _extract_dishes_json(week_data, target_date)
        if dishes:
            return dishes
    except Exception as exc:
        logger.warning("JSON menu lookup failed: %s", exc)

    # Fallback path: user's RSS feed.
    try:
        return _rss_dishes_for_date(target_date)
    except Exception as exc:
        logger.warning("RSS menu lookup failed: %s", exc)
        raise


def join_spanish(items):
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return "{0} y {1}".format(items[0], items[1])
    return "{0} y {1}".format(", ".join(items[:-1]), items[-1])


def date_phrase(target, today):
    if target == today:
        return "Hoy"
    if target == today + timedelta(days=1):
        return "Mañana"
    return "El {0} {1} de {2}".format(
        WEEKDAYS_ES[target.weekday()],
        target.day,
        MONTHS_ES[target.month - 1],
    )


def menu_answer(target_date):
    today = stockholm_today()
    dishes = get_menu(target_date)
    when = date_phrase(target_date, today)

    if not dishes:
        speech = "{0} no hay ningún menú publicado para el colegio.".format(when)
        return speech, speech

    menu = join_spanish(dishes)
    speech = "{0}, en el colegio hay {1}.".format(when, menu)
    card = "{0}:\n{1}".format(when, "\n".join("• " + dish for dish in dishes))
    return speech, card


def parse_alexa_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def response_with_menu(handler_input, target_date):
    speech, card = menu_answer(target_date)
    handler_input.response_builder.speak(speech).set_card(SimpleCard("Menú de Ada", card))
    return handler_input.response_builder.response


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        return response_with_menu(handler_input, stockholm_today())


class MenuForDateIntentHandler(AbstractRequestHandler):
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
    def can_handle(self, handler_input):
        return is_intent_name("NextSchoolMenuIntent")(handler_input)

    def handle(self, handler_input):
        start = stockholm_today()
        for offset in range(0, 11):
            candidate = start + timedelta(days=offset)
            try:
                dishes = get_menu(candidate)
            except Exception:
                continue
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
        logger.exception("Unhandled error in Menú de Ada: %s", exception)
        speech = (
            "La skill funciona, pero no he podido consultar el menú de Skolmat ahora mismo."
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
