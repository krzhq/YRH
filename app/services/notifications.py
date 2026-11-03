import asyncio
import html
import json
import logging
from datetime import datetime, timedelta, timezone
from app.database.store import now

log = logging.getLogger(__name__)

def render(table, payload):
    p = {k: html.escape(str(v)) for k, v in payload.items() if v is not None}
    if table == 'restaurant_import':
        return f"<b>Импорт заведений</b>\n\nДобавлено: {p['inserted']}\nОбновлено: {p['updated']}\nБез изменений: {p['unchanged']}\nОтклонено: {p['rejected']}\nВсего в базе: {p['database_total']}"
    title = '<b>Обновление базы данных</b>\n\nТаблица: ' + html.escape(table) + '\nДействие: INSERT\n\n'
    if table == 'users':
        return title + f"Новый аккаунт\nID: {p['id']}\nИмя: {p['username']}\nВозраст: {p['age']}\nРоль: {p['role']}\nВремя (UTC): {p['time']}"
    if table == 'restaurants':
        return title + f"ID: {p['id']}\nНазвание: {p['name']}\nРайон: {p['district']}\nСредняя цена: {p['average_price']} KZT\nВремя (UTC): {p['time']}"
    return title + f"ID пользователя: {p['user_id']}\nДействие: {p['action']}\nБюджет: {p.get('budget', '—')}\nВремя (UTC): {p['time']}"

class NotificationDispatcher:
    def __init__(self, store, bot):
        self.store, self.bot = store, bot
        self.lock = asyncio.Lock()

    async def dispatch(self):
        # One dispatcher per process. A crash after Telegram accepts a message but
        # before the acknowledgement is committed can still cause a duplicate.
        async with self.lock:
            async with self.store.connect() as db:
                rows = await (await db.execute("SELECT o.*, a.telegram_id FROM notification_outbox o JOIN users u ON u.id=o.admin_id JOIN account_owners a ON a.user_id=u.id WHERE u.role='admin' AND o.delivered_at IS NULL AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=?) ORDER BY o.id LIMIT 100", (now(),))).fetchall()
                for row in rows:
                    try:
                        await self.bot.send_message(row['telegram_id'], render(row['table_name'], json.loads(row['payload'])))
                    except Exception as exc:
                        log.warning('Notification delivery failed (outbox id %s): %s', row['id'], type(exc).__name__)
                        delay = min(3600, 30 * (2 ** min(row['attempts'], 7)))
                        next_time = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                        await db.execute('UPDATE notification_outbox SET attempts=attempts+1,next_attempt_at=? WHERE id=? AND delivered_at IS NULL', (next_time,row['id']))
                    else:
                        await db.execute('UPDATE notification_outbox SET delivered_at=?,attempts=attempts+1 WHERE id=? AND delivered_at IS NULL', (now(),row['id']))
                    await db.commit()

    async def run(self):
        while True:
            try:
                await self.dispatch()
            except Exception:
                log.exception('Notification dispatcher failed')
            await asyncio.sleep(10)

