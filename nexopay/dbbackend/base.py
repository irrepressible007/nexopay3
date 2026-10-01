"""
MySQL/MariaDB backend that doesn't need the server's time-zone tables.

With USE_TZ, Django converts datetimes inside SQL (admin date drill-down, TruncDate,
__date/__year lookups) with CONVERT_TZ(value, 'UTC', 'Asia/Dhaka'). Named zones only
work once the database server has loaded its time-zone tables, which shared hosts
(cPanel) usually haven't: CONVERT_TZ then returns NULL, the admin's event list crashes
and per-day charts come out empty. A zone whose offset never changes (UTC, Asia/Dhaka
since 2009) is sent as '+00:00' / '+06:00' instead, which MySQL understands without
any tables. Zones with daylight saving keep their name (and still need the tables).
"""
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from django.db.backends.mysql import base, operations


@lru_cache(maxsize=None)
def fixed_offset(tzname):
    """'+06:00' for a zone with one UTC offset all year (last, this and next year), else None."""
    if not tzname or tzname[0] in "+-":
        return None
    try:
        zone = ZoneInfo(tzname)
    except Exception:
        return None
    year = datetime.now().year
    offsets = {datetime(y, m, 1, tzinfo=zone).utcoffset() for y in (year - 1, year, year + 1) for m in (1, 4, 7, 10)}
    if len(offsets) != 1:
        return None
    minutes = int(offsets.pop().total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


class DatabaseOperations(operations.DatabaseOperations):
    def _prepare_tzname_delta(self, tzname):
        return fixed_offset(tzname) or super()._prepare_tzname_delta(tzname)

    def _convert_sql_to_tz(self, sql, params, tzname):
        sql, params = super()._convert_sql_to_tz(sql, params, tzname)
        if sql.startswith("CONVERT_TZ("):  # the connection's own zone (UTC) is the second-to-last parameter
            *rest, source, target = params
            params = (*rest, fixed_offset(source) or source, target)
        return sql, params


class DatabaseWrapper(base.DatabaseWrapper):
    ops_class = DatabaseOperations
