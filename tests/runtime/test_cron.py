from datetime import datetime

import pytest

from tg_ifttt.cron import CronExpressionError, CronSchedule


def test_cron_supports_ranges_lists_and_steps():
    schedule = CronSchedule.parse("*/5 9-10 1,15 * 1-5")

    assert schedule.matches(datetime(2026, 6, 1, 9, 10))
    assert not schedule.matches(datetime(2026, 6, 1, 9, 11))
    assert not schedule.matches(datetime(2026, 6, 6, 9, 10))


@pytest.mark.parametrize("expression", ["* * * *", "61 * * * *", "*/0 * * * *", "5-1 * * * *"])
def test_cron_rejects_invalid_expressions(expression):
    with pytest.raises(CronExpressionError):
        CronSchedule.parse(expression)
