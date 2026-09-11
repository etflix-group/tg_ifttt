"""Small, dependency-free parser for the five-field cron format."""

import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Set


class CronExpressionError(ValueError):
    """Raised when a workflow contains an invalid cron expression."""


class ScheduleConfigError(ValueError):
    """Raised when a fixed-time schedule contains invalid values."""


def _parse_number(value: str, minimum: int, maximum: int, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CronExpressionError("invalid %s cron value: %s" % (field, value)) from exc
    if number < minimum or number > maximum:
        raise CronExpressionError(
            "%s cron value must be between %d and %d" % (field, minimum, maximum)
        )
    return number


def _expand_part(part: str, minimum: int, maximum: int, field: str) -> Iterable[int]:
    if not part:
        raise CronExpressionError("empty %s cron segment" % field)
    raw_range, separator, raw_step = part.partition("/")
    if separator:
        try:
            step = int(raw_step)
        except (TypeError, ValueError) as exc:
            raise CronExpressionError("invalid %s cron step: %s" % (field, raw_step)) from exc
        if step <= 0:
            raise CronExpressionError("%s cron step must be positive" % field)
    else:
        step = 1

    if raw_range == "*":
        start, end = minimum, maximum
    elif "-" in raw_range:
        pieces = raw_range.split("-")
        if len(pieces) != 2:
            raise CronExpressionError("invalid %s cron range: %s" % (field, raw_range))
        start = _parse_number(pieces[0], minimum, maximum, field)
        end = _parse_number(pieces[1], minimum, maximum, field)
        if start > end:
            raise CronExpressionError("%s cron range must be ascending" % field)
    else:
        start = _parse_number(raw_range, minimum, maximum, field)
        end = start
        if separator:
            raise CronExpressionError("a stepped %s cron value must use * or a range" % field)

    return range(start, end + 1, step)


def _parse_field(value: str, minimum: int, maximum: int, field: str) -> Set[int]:
    if not isinstance(value, str) or not value.strip():
        raise CronExpressionError("%s cron field must not be empty" % field)
    values: Set[int] = set()
    for part in value.split(","):
        values.update(_expand_part(part.strip(), minimum, maximum, field))
    if not values:
        raise CronExpressionError("%s cron field produced no values" % field)
    return values


@dataclass(frozen=True)
class CronSchedule:
    minute: Set[int]
    hour: Set[int]
    day_of_month: Set[int]
    month: Set[int]
    day_of_week: Set[int]

    @classmethod
    def parse(cls, expression: str) -> "CronSchedule":
        if not isinstance(expression, str):
            raise CronExpressionError("cron expression must be a string")
        fields = expression.split()
        if len(fields) != 5:
            raise CronExpressionError("cron expression must contain five fields")
        return cls(
            minute=_parse_field(fields[0], 0, 59, "minute"),
            hour=_parse_field(fields[1], 0, 23, "hour"),
            day_of_month=_parse_field(fields[2], 1, 31, "day-of-month"),
            month=_parse_field(fields[3], 1, 12, "month"),
            day_of_week=_parse_field(fields[4], 0, 7, "day-of-week"),
        )

    def matches(self, value: datetime) -> bool:
        if value.minute not in self.minute:
            return False
        if value.hour not in self.hour or value.month not in self.month:
            return False
        # Python uses Monday=0 while cron convention uses Sunday=0 or 7.
        cron_weekday = (value.weekday() + 1) % 7
        day_of_month_match = value.day in self.day_of_month
        day_of_week_match = cron_weekday in self.day_of_week or (
            cron_weekday == 0 and 7 in self.day_of_week
        )
        dom_is_wildcard = len(self.day_of_month) == 31
        dow_is_wildcard = len(self.day_of_week) == 7
        if not dom_is_wildcard and not dow_is_wildcard:
            return day_of_month_match or day_of_week_match
        return day_of_month_match and day_of_week_match


def _schedule_integer(config: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ScheduleConfigError("%s must be an integer from %d to %d" % (key, minimum, maximum))
    return value


@dataclass(frozen=True)
class ScheduleOccurrence:
    scheduled_at: datetime
    random_seconds: int


@dataclass(frozen=True)
class FixedTimeSchedule:
    """Run every N calendar days at a fixed local time, with optional jitter."""

    interval_days: int
    hour: int
    minute: int
    second: int
    random_seconds: bool = False
    anchor_date: date = date(1970, 1, 1)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "FixedTimeSchedule":
        if not isinstance(config, Mapping):
            raise ScheduleConfigError("schedule config must be a mapping")
        raw_anchor = config.get("anchor_date", "1970-01-01")
        if not isinstance(raw_anchor, str):
            raise ScheduleConfigError("anchor_date must be an ISO date")
        try:
            anchor_date = date.fromisoformat(raw_anchor)
        except ValueError as exc:
            raise ScheduleConfigError("anchor_date must be an ISO date") from exc
        random_enabled = config.get("random_seconds", False)
        if not isinstance(random_enabled, bool):
            raise ScheduleConfigError("random_seconds must be a boolean")
        return cls(
            interval_days=_schedule_integer(config, "interval_days", 1, 3650),
            hour=_schedule_integer(config, "hour", 0, 23),
            minute=_schedule_integer(config, "minute", 0, 59),
            second=_schedule_integer(config, "second", 0, 59),
            random_seconds=random_enabled,
            anchor_date=anchor_date,
        )

    def _random_offset(self, workflow_id: str, trigger_index: int, occurrence_date: date) -> int:
        if not self.random_seconds:
            return 0
        seed = "%s:%d:%s" % (workflow_id, trigger_index, occurrence_date.isoformat())
        stable_seed = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")
        return random.Random(stable_seed).randint(0, 59 - self.second)

    def occurrence_at(
        self,
        workflow_id: str,
        trigger_index: int,
        current: datetime,
    ) -> Optional[ScheduleOccurrence]:
        local_current = current if current.tzinfo is not None else current.astimezone()
        occurrence_date = local_current.date()
        elapsed_days = (occurrence_date - self.anchor_date).days
        if elapsed_days < 0 or elapsed_days % self.interval_days:
            return None
        offset = self._random_offset(workflow_id, trigger_index, occurrence_date)
        scheduled_at = datetime.combine(
            occurrence_date,
            time(self.hour, self.minute, self.second + offset),
            tzinfo=local_current.tzinfo,
        )
        return ScheduleOccurrence(scheduled_at, offset)

    def is_due(
        self,
        workflow_id: str,
        trigger_index: int,
        current: datetime,
        grace_seconds: float = 60.0,
    ) -> bool:
        occurrence = self.occurrence_at(workflow_id, trigger_index, current)
        if occurrence is None:
            return False
        elapsed = (current - occurrence.scheduled_at).total_seconds()
        return 0 <= elapsed < grace_seconds


def scheduled_slot(expression: str, value: datetime) -> str:
    """Return a stable UTC minute slot for idempotent scheduled runs."""

    CronSchedule.parse(expression)
    return "%s:%s" % (
        expression,
        value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%z"),
    )
