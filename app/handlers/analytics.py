import html
from aiogram import F,Router
from aiogram.types import CallbackQuery,BufferedInputFile,InlineKeyboardButton,InlineKeyboardMarkup
from app.services.analytics import metrics,csv_bytes,event_csv,statistics_csv,tinder_csv

router=Router()

@router.callback_query(F.data.startswith('analytics:'))
async def analytics(q:CallbackQuery,store):
    if not q.message or q.message.chat.type != 'private': await q.answer('Откройте бота в личном чате.',show_alert=True); return
    user=await store.get_user(q.from_user.id)
    if not user or user['role']!='admin': await q.answer('Доступ запрещён.',show_alert=True); return
    parts=q.data.split(':'); period=parts[1] if len(parts)>1 else 'all'
    if period not in ('today','7','30','all'): await q.answer(); return
    m=await metrics(store,period)
    if len(parts)>2 and parts[2]=='csv':
        await q.answer(); await q.message.answer_document(BufferedInputFile(csv_bytes(m),filename='analytics.csv'),caption='Агрегированная статистика'); return
    if len(parts)>2 and parts[2]=='events':
        await q.answer(); await q.message.answer_document(BufferedInputFile(await event_csv(store,period),filename='events.csv'),caption='События без идентификаторов пользователей, до 50 000 записей'); return
    if len(parts)>2 and parts[2]=='ratings':
        await q.answer(); await q.message.answer_document(BufferedInputFile(await statistics_csv(store,period),filename='statistics.csv'),caption='Оценки Find Restaurant'); return
    if len(parts)>2 and parts[2]=='tinder':
        await q.answer(); await q.message.answer_document(BufferedInputFile(await tinder_csv(store,period),filename='tinder_actions.csv'),caption='Действия Tinder'); return
    def ratio(n,d): return f'{n/d*100:.1f}%' if d else 'нет данных'
    def top(rows): return ', '.join(f'{html.escape(str(row[0])[:70])} ({row[1]})' for row in rows[:3]) or 'нет данных'
    def avg_groups(rows): return ', '.join(f'{html.escape(str(label)[:70])}: {avg:.2f} (n={n})' for label,avg,n in rows[:3]) or 'нет данных'
    text=(f"<b>Аналитика</b>\n\nПользователи: {m['users']}\nЗаведения: {m['restaurants']}\n"
          f"Анкеты: начато {m['started']}, завершено {m['completed']} ({ratio(m['completed'],m['started'])})\n"
          f"Рекомендации: {m['results']}\nОценок: {m['feedback']}\nСредняя оценка: {m['average']:.2f}\n" if m['average'] is not None else
          f"<b>Аналитика</b>\n\nПользователи: {m['users']}\nЗаведения: {m['restaurants']}\nАнкеты: начато {m['started']}, завершено {m['completed']} ({ratio(m['completed'],m['started'])})\nРекомендации: {m['results']}\nОценок: 0\nСредняя оценка: нет данных\n")
    median=f"{m['median']:.1f}" if m['median'] is not None else 'нет данных'
    dist=' · '.join(f"{i}★: {m['star_distribution'][str(i)]}" for i in range(1,6))
    text+=f"Пользователи поиска: {m['search_users']}\nПросмотры: {m['views']}\n\n<b>Оценки Find Restaurant</b>\nОценивших пользователей: {m['rating_users']}\nМедиана: {median}\n{dist}\nОценки 4–5: {ratio(m['positive'],m['feedback'])}\nОценки 1–2: {ratio(m['negative'],m['feedback'])}\nПричины 1–2: {top(m['negative_reasons'])}\nОценены результаты периода: {m['rated_results']} из {m['results']} ({ratio(m['rated_results'],m['results'])})\n\nСреднее по дням Алматы: {avg_groups(m['average_by_date'])}\nПо заведениям: {avg_groups(m['average_by_restaurant'])}\nПо кухне: {avg_groups(m['average_by_cuisine'])}\nПо бюджету: {avg_groups(m['average_by_budget'])}\nПо цвету: {avg_groups(m['average_by_color'])}\n\n<b>Tinder</b>\nНравится: {m['likes']}, пропущено: {m['dislikes']} ({ratio(m['likes'],m['likes']+m['dislikes'])})\nИзбранное сейчас: {m['favorites']} у {m['favorite_users']} пользователей\nАктивных: {m['active']}; вернулись в разные дни Алматы: {m['returning']} ({ratio(m['returning'],m['active'])})\n\nЧаще нравятся: {top(m['most_liked'])}\nЧаще рекомендуются: {top(m['most_recommended'])}"
    buttons=[[('Сегодня','analytics:today'),('7 дней','analytics:7')],[('30 дней','analytics:30'),('Всё время','analytics:all')],[('Итоги CSV',f'analytics:{period}:csv'),('Оценки CSV',f'analytics:{period}:ratings')],[('События CSV',f'analytics:{period}:events'),('Tinder CSV',f'analytics:{period}:tinder')],[('← Назад','menu')]]
    await q.answer(); await q.message.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t,callback_data=d) for t,d in row] for row in buttons]))
