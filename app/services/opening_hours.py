"""Only explicit daily schedules are interpreted; bare ranges are unknown."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

def open_status(schedule, visit):
    if not isinstance(schedule,str) or not schedule.strip() or not visit: return None
    text=schedule.lower().strip().rstrip(',').strip()
    if text in ('круглосуточно','24/7','ежедневно круглосуточно'): return True
    if not re.search(r'ежедневно|пн\s*[-–—]\s*вс',text): return None
    ranges=re.findall(r'(?<!\d)([0-2]\d):([0-5]\d)\s*[-–—]\s*([0-2]\d):([0-5]\d)(?!\d)',text)
    if len(ranges)!=1: return None
    sh,sm,eh,em=map(int,ranges[0])
    if sh>23 or eh>23: return None
    try:
        dt=datetime.fromisoformat(visit) if isinstance(visit,str) else visit
        if dt.tzinfo is None: return None
        local=dt.astimezone(ZoneInfo('Asia/Almaty'))
    except (TypeError,ValueError,AttributeError): return None
    current=local.hour*60+local.minute; start=sh*60+sm; end=eh*60+em
    if start==end: return None
    return start<=current<end if start<end else current>=start or current<end
