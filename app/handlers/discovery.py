import asyncio
import html
import io
import json
import re
import ipaddress
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from PIL import Image, ImageDraw
from app.services import discovery as svc
from app.services.color_families import COLORS, hex_to_rgb

router=Router()

class Quiz(StatesGroup):
    active=State()
    input=State()

class Feedback(StatesGroup):
    other=State()

class Swipe(CallbackData, prefix='sw'):
    session: int
    restaurant: int
    action: str

def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t,callback_data=d) for t,d in row] for row in rows])

def h(value): return html.escape(str(value)[:160]) if value not in (None,'') else 'не указано'

def text_card(row):
    lines=[f"<b>{h(row['name'])}</b>",f"Тип: {h(row['restaurant_type'])}",f"Кухня: {h(row['menu_vibe'])}",f"Адрес: {h(row['address'])}",f"Средний чек: {h(row['average_bill'])}"]
    if row['rating'] is not None: lines.append(f"Рейтинг: {h(row['rating'])} / 5")
    if row['reviews_count'] is not None: lines.append(f"Отзывы: {h(row['reviews_count'])}")
    if row['description']: lines.append('\n'+h(row['description'][:400]))
    return '\n'.join(lines)

def palette_image(value,highlight=None,family=None):
    try: colors=json.loads(value or '[]')
    except (TypeError,ValueError): colors=[]
    colors=[c for c in colors if hex_to_rgb(c)][:8]
    if not colors: return None
    image=Image.new('RGB',(max(450,len(colors)*105),180),'white'); draw=ImageDraw.Draw(image)
    for i,c in enumerate(colors):
        x=15+i*105; draw.rectangle((x,12,x+90,100),fill=c,outline='black',width=4 if c==highlight else 1); draw.text((x,110),c,fill='black')
    if family in COLORS:
        draw.text((15,145),'Selected: '+family+'   Closest: '+(highlight or 'unknown'),fill='black')
    output=io.BytesIO(); image.save(output,format='PNG'); return output.getvalue()

def safe_photo_url(value):
    if not isinstance(value,str): return False
    try:
        parsed=urlsplit(value); host=parsed.hostname
        if parsed.scheme not in ('http','https') or not host or parsed.username or parsed.password: return False
        if host.lower()=='localhost' or host.lower().endswith(('.localhost','.local')): return False
        try: return ipaddress.ip_address(host).is_global
        except ValueError: return '.' in host
    except ValueError: return False

async def card(message,row,buttons,extra='',highlight=None,family=None,show_preference=True):
    caption=text_card(row)+extra
    overflow=''
    if len(caption)>1000:
        caption=text_card(row)
        overflow=extra
    try: photos=json.loads(row['photos'] or '[]')
    except (TypeError,ValueError): photos=[]
    if not isinstance(photos,list): photos=[]
    urls=[row['photo']]+photos
    sent=False
    for url in list(dict.fromkeys(x for x in urls if safe_photo_url(x)))[:5]:
        try:
            await asyncio.wait_for(message.answer_photo(url,caption=caption,reply_markup=None if overflow else buttons),timeout=12); sent=True; break
        except Exception: continue
    if not sent: await message.answer(caption,reply_markup=None if overflow else buttons)
    if overflow: await message.answer(overflow,reply_markup=buttons)
    try:
        image=await asyncio.to_thread(palette_image,row['color_palette_hex'],highlight,family)
        if image:
            label=COLORS[family][0] if family in COLORS else 'не выбран'
            caption=f'Палитра заведения · выбранный цвет: {label}' if show_preference else 'Палитра заведения'
            await message.answer_photo(BufferedInputFile(image,filename='palette.png'),caption=caption)
    except Exception:
        pass

async def current_user(q,store):
    if not q.message or q.message.chat.type != 'private':
        await q.answer('Откройте бота в личном чате.',show_alert=True)
        return None
    user=await store.get_user(q.from_user.id)
    if not user: await q.answer('Сначала войдите в аккаунт.',show_alert=True)
    return user

async def draw_step(q,state,store):
    data=await state.get_data(); step=data['step']; prefs=data.get('prefs',{})
    if step==0:
        rows=await svc.restaurants(store); names=set()
        for row in rows:
            for part in re.split(r'[,;/]',row['menu_vibe'] or ''):
                part=part.strip().lower().replace(' кухня','')
                if re.fullmatch(r'[а-яё-]{4,24}ая',part): names.add(part)
        opts=[(name.capitalize(),f'dq:v:{name}') for name in sorted(names)[:30]]+[('Любая кухня','dq:v:any')]
        title='Какую кухню вы предпочитаете?'
    elif step==1: opts=[('Кафе','dq:v:кафе'),('Ресторан','dq:v:ресторан'),('Любое заведение','dq:v:any')]; title='Какой тип заведения вы ищете?'
    elif step==2: opts=[('Уютная','dq:v:cozy'),('Спокойная','dq:v:cozy'),('Современная','dq:v:modern'),('Романтичная','dq:v:romantic'),('Премиальная','dq:v:premium'),('Для компании','dq:v:group'),('Любая','dq:v:any')]; title='Какая атмосфера вам ближе?'
    elif step==3:
        opts=[(v,f'dq:v:{i}') for i,v in enumerate(['Алматинский','Байконурский','Есильский','Нура','Сарайшык','Сарыарка'])]+[('Любой район','dq:v:any')]; title='В каком районе Астаны?\n\nРайоны большинства заведений не подтверждены; поиск по выбранному району может быть неточным.'
    elif step==4: opts=[('До 3 000 ₸','dq:v:3000'),('3 000–5 000 ₸','dq:v:5000'),('5 000–8 000 ₸','dq:v:7000'),('8 000–12 000 ₸','dq:v:10000'),('От 12 000 ₸','dq:v:12000'),('Ввести сумму','dq:input:budget'),('Любой бюджет','dq:v:any')]; title='Какой примерный бюджет на человека?'
    elif step==5: opts=[('Сейчас','dq:v:now'),('Сегодня позже','dq:v:later'),('Завтра','dq:v:tomorrow'),('Указать дату и время','dq:input:time'),('Не имеет значения','dq:v:any')]; title='Когда планируете посетить заведение?\n\nВремя работы необходимо уточнить у заведения.'
    else:
        opts=[(label,'dq:v:'+name) for name,(label,_) in COLORS.items()]+[('Любой цвет','dq:v:any')]
        title='Цветовая палитра\n\nМы подобрали заведения по вашим предпочтениям. Выберите цвет, который соответствует вашему настроению.'
    rows=[opts[i:i+2] for i in range(0,len(opts),2)]
    rows.append(([('← Назад','dq:back')] if step else [])+[('Отмена','dq:cancel')])
    try: await q.message.edit_text(f'<b>Шаг {step+1} из 7</b>\n\n{title}',reply_markup=keyboard(rows))
    except Exception: await q.message.answer(f'<b>Шаг {step+1} из 7</b>\n\n{title}',reply_markup=keyboard(rows))

@router.callback_query(F.data == 'discover')
async def start_quiz(q:CallbackQuery,state:FSMContext,store):
    user=await current_user(q,store)
    if not user: return
    await state.clear(); session=await svc.start_search(store,user['id']); await state.set_state(Quiz.active)
    await state.update_data(step=0,prefs={},session=session)
    await q.answer(); await draw_step(q,state,store)

@router.callback_query(F.data == 'quiz:resume')
async def resume_quiz(q:CallbackQuery,state:FSMContext,store):
    if not await current_user(q,store): return
    data=await state.get_data()
    if not (await state.get_state() or '').startswith('Quiz:') or 'step' not in data:
        await q.answer('Сохранённая анкета не найдена.',show_alert=True); return
    await state.set_state(Quiz.active); await q.answer(); await draw_step(q,state,store)

@router.callback_query(F.data.startswith('dq:'))
async def quiz_callback(q:CallbackQuery,state:FSMContext,store):
    user=await current_user(q,store)
    if not user: return
    data=await state.get_data()
    if await state.get_state() not in (Quiz.active.state,Quiz.input.state) or 'session' not in data:
        await q.answer('Этот поиск завершён. Начните новый.',show_alert=True); return
    parts=q.data.split(':',2); command=parts[1]; step=data['step']; prefs=data['prefs']
    if command=='cancel':
        await state.clear(); await q.answer(); await q.message.edit_text('Поиск отменён.',reply_markup=keyboard([[('Главное меню','menu')]])); return
    if command=='back':
        await state.set_state(Quiz.active); await state.update_data(step=max(0,step-1)); await q.answer(); await draw_step(q,state,store); return
    if command=='backcolor':
        await state.set_state(Quiz.active); await q.answer(); await draw_step(q,state,store); return
    if command=='input':
        if step not in (4,5): await q.answer('Этот шаг уже изменился.',show_alert=True); return
        await state.set_state(Quiz.input); await q.answer(); await q.message.answer('Введите сумму целым числом.' if step==4 else 'Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ (Астана).',reply_markup=keyboard([[('← Назад','dq:back'),('Отмена','dq:cancel')]])); return
    if command!='v' or len(parts)!=3: await q.answer(); return
    value=parts[2]; keys=['cuisine','type','vibe','district','budget','visit_datetime','color']; key=keys[step]
    if step==0: prefs[key]=[] if value=='any' else [value]
    elif step==1:
        if value not in ('any','кафе','ресторан'): await q.answer(); return
        prefs[key]=None if value=='any' else value
    elif step==2:
        if value not in ('any','cozy','modern','romantic','premium','group'): await q.answer(); return
        prefs[key]=[] if value=='any' else [value]
    elif step==3:
        districts=['Алматинский','Байконурский','Есильский','Нура','Сарайшык','Сарыарка']
        if value!='any' and (not value.isdigit() or int(value)>=len(districts)): await q.answer(); return
        prefs[key]=None if value=='any' else districts[int(value)]
    elif step==4:
        if value!='any' and (not value.isdigit() or not 0<int(value)<=1000000): await q.answer(); return
        prefs[key]=None if value=='any' else int(value)
    elif step==5:
        if value not in ('now','later','tomorrow','any'): await q.answer(); return
        local=datetime.now(ZoneInfo('Asia/Almaty'))
        chosen=local+timedelta(hours=3 if value=='later' else 24 if value=='tomorrow' else 0)
        if value=='later' and chosen.date()!=local.date(): chosen=local.replace(hour=23,minute=59,second=0,microsecond=0)
        prefs[key]=None if value=='any' else chosen.isoformat()
    else:
        if value!='any' and value not in COLORS: await q.answer(); return
        prefs[key]=None if value=='any' else value
    actions=['cuisine_selected','type_selected','vibe_selected','district_selected','budget_selected','visit_time_selected','colors_selected']
    await svc.save_step(store,user['id'],data['session'],actions[step],prefs)
    if step==5:
        venues=await svc.restaurants(store); base=await asyncio.to_thread(svc.base_candidates,venues,prefs)
        await state.update_data(base_ids=[v['id'] for v,_ in base])
    await state.update_data(prefs=prefs)
    if step<6:
        await state.update_data(step=step+1); await q.answer(); await draw_step(q,state,store); return
    data=await state.get_data(); venues=await svc.restaurants(store); allowed=set(data.get('base_ids',[]))
    base=await asyncio.to_thread(svc.base_candidates,[v for v in venues if v['id'] in allowed],prefs)
    results=await asyncio.to_thread(svc.refine_color,base,prefs['color'])
    if not results:
        await q.answer()
        if not base:
            await q.message.edit_text('<b>По выбранным условиям заведений не найдено</b>\n\nИзмените кухню, тип или бюджет и попробуйте снова.',reply_markup=keyboard([[('Изменить фильтры','discover')],[('Главное меню','menu')]])); return
        await q.message.edit_text('<b>По выбранному цвету совпадений нет</b>\n\nМы нашли заведения по основным предпочтениям, но не нашли подтверждённого совпадения с выбранным цветом.',reply_markup=keyboard([[('Выбрать другой цвет','dq:backcolor')],[('Показать без цвета','dq:v:any')],[('Изменить фильтры','discover')]])); return
    await svc.save_results(store,user['id'],data['session'],prefs,results); await state.clear(); await q.answer()
    await show_result(q.message,store,user['id'],data['session'],1)

@router.message(StateFilter(Quiz.input), lambda message: not message.text or not message.text.startswith('/'))
async def quiz_input(message:Message,state:FSMContext,store):
    if message.chat.type!='private': return
    user=await store.get_user(message.from_user.id)
    if not user: await state.clear(); return
    data=await state.get_data(); text=(message.text or '').strip(); prefs=data['prefs']; step=data['step']
    if step==4:
        if not text.isascii() or not text.isdigit() or not 0<int(text)<=1000000:
            await message.answer('Введите положительную сумму до 1 000 000.'); return
        prefs['budget']=int(text); action='budget_selected'
    elif step==5:
        try: prefs['visit_datetime']=datetime.strptime(text,'%d.%m.%Y %H:%M').replace(tzinfo=ZoneInfo('Asia/Almaty')).isoformat()
        except ValueError: await message.answer('Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ.'); return
        action='visit_time_selected'
    else: await state.clear(); return
    await svc.save_step(store,user['id'],data['session'],action,prefs)
    if step==5:
        base=await asyncio.to_thread(svc.base_candidates,await svc.restaurants(store),prefs); await state.update_data(base_ids=[v['id'] for v,_ in base])
    await state.update_data(prefs=prefs,step=step+1); await state.set_state(Quiz.active)
    # Reuse the same step renderer with a fresh, editable message.
    stub=await message.answer('Продолжим…')
    class Adapter:
        pass
    q=Adapter(); q.message=stub
    await draw_step(q,state,store)

async def show_result(message,store,user_id,session,rank):
    row=await svc.get_result(store,user_id,session,rank)
    if not row: await message.answer('Больше вариантов нет.',reply_markup=keyboard([[('Новый поиск','discover'),('Главное меню','menu')]])); return
    match=json.loads(row['criteria']); reasons='\n'.join('• '+h(x) for x in match.get('explanations',[])) or 'Данных недостаточно для объяснения совпадения.'
    if row['color_hex']: reasons += '\n• Найдены оттенки выбранного цвета.'
    extra=f"\n\n<b>Почему подходит</b>\n{reasons}\nСовпадение предпочтений: {round(row['score']*100)}%\nВремя работы требует уточнения.\n\n<b>Оцените результат подбора</b>\nНасколько предложенное заведение соответствует вашим предпочтениям?"
    buttons=keyboard([[('✓ Хочу сходить',f'fav:add:{row["id"]}')],[('Следующий вариант →',f'result:{session}:{rank+1}')],[('Все результаты',f'results:{session}'),('Подробнее',f'detail:{row["id"]}')],[('Новый поиск','discover')],[(f'{i} ★',f'rate:{row["result_id"]}:{i}') for i in range(1,6)]])
    async with store.connect() as db:
        await svc.log_event(db,user_id,'recommendation_viewed',row['id'],{'session_id':session}); await db.commit()
    prefs=json.loads(row['session_preferences'])
    await card(message,row,buttons,extra,row['color_hex'],prefs.get('color'))

@router.callback_query(F.data.startswith('result:') | F.data.startswith('results:'))
async def result_navigation(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    parts=q.data.split(':')
    try: session=int(parts[1]); rank=int(parts[2]) if len(parts)>2 else 1
    except (ValueError,IndexError): await q.answer(); return
    if parts[0]=='results':
        async with store.connect() as db:
            rows=await (await db.execute('SELECT r.name,x.rank_position FROM recommendation_results x JOIN recommendation_sessions s ON s.id=x.session_id JOIN restaurants r ON r.id=x.restaurant_id WHERE s.id=? AND s.user_id=? ORDER BY x.rank_position LIMIT 20',(session,user['id']))).fetchall()
        if not rows: await q.answer('Результаты не найдены.',show_alert=True); return
        await q.answer(); await q.message.answer('<b>Результаты</b>\n\n'+'\n'.join(f"{r['rank_position']}. {h(r['name'])}" for r in rows),reply_markup=keyboard([[('Открыть первый','result:'+str(session)+':1')]])); return
    await q.answer(); await show_result(q.message,store,user['id'],session,rank)

@router.callback_query(F.data.startswith('rate:'))
async def rate(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    try: _,result,rating=q.data.split(':'); success=await svc.feedback(store,user['id'],int(result),int(rating))
    except (ValueError,IndexError): success=False
    except Exception:
        await q.answer('Не удалось сохранить оценку. Попробуйте ещё раз.',show_alert=True); return
    await q.answer('Оценка сохранена.' if success else 'Оценка недоступна.',show_alert=not success)
    if success and int(rating)<=3:
        choices=[('Цена','price'),('Атмосфера','vibe'),('Кухня','cuisine'),('Расположение','location'),('Цветовая палитра','color'),('Другое','other'),('Пропустить','skip')]
        await q.message.answer('<b>Что можно улучшить?</b>\n\nМожно пропустить этот шаг.',reply_markup=keyboard([[(label,f'reason:{result}:{key}')] for label,key in choices]))

@router.callback_query(F.data.startswith('reason:'))
async def reason_callback(q:CallbackQuery,state:FSMContext,store):
    user=await current_user(q,store)
    if not user: return
    try: _,result,reason=q.data.split(':'); result=int(result)
    except (ValueError,IndexError): await q.answer(); return
    labels={'price':'Цена','vibe':'Атмосфера','cuisine':'Кухня','location':'Расположение','color':'Цветовая палитра'}
    if reason=='skip': await q.answer('Пропущено'); return
    if reason=='other':
        async with store.connect() as db:
            row=await (await db.execute('SELECT 1 FROM statistics WHERE user_id=? AND recommendation_result_id=? AND stars<=3',(user['id'],result))).fetchone()
        if not row: await q.answer('Оценка не найдена.',show_alert=True); return
        await state.clear(); await state.set_state(Feedback.other); await state.update_data(feedback_result=result)
        await q.answer(); await q.message.answer('Опишите причину одним сообщением, до 300 символов.',reply_markup=keyboard([[('Отмена','menu')]])); return
    if reason not in labels: await q.answer(); return
    saved=await svc.feedback_reason(store,user['id'],result,labels[reason])
    await q.answer('Спасибо, причина сохранена.' if saved else 'Оценка не найдена.',show_alert=not saved)

@router.message(StateFilter(Feedback.other), lambda message: not message.text or not message.text.startswith('/'))
async def reason_text(message:Message,state:FSMContext,store):
    if message.chat.type!='private': return
    user=await store.get_user(message.from_user.id); data=await state.get_data(); text=(message.text or '').strip()
    if not user: await state.clear(); return
    if not 1<=len(text)<=300: await message.answer('Введите от 1 до 300 символов или отмените ввод.'); return
    saved=await svc.feedback_reason(store,user['id'],data.get('feedback_result'),text)
    await state.clear(); await message.answer('Спасибо, причина сохранена.' if saved else 'Оценка не найдена.',reply_markup=keyboard([[('Главное меню','menu')]]))

@router.callback_query(F.data.startswith('fav:'))
async def favorites_action(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    try: _,action,restaurant=q.data.split(':'); restaurant=int(restaurant)
    except ValueError: await q.answer(); return
    if action not in ('add','remove'): await q.answer(); return
    changed=await svc.favorite(store,user['id'],restaurant,action=='add')
    await q.answer(('Добавлено в избранное.' if changed else 'Уже в избранном.') if action=='add' else ('Удалено.' if changed else 'Уже удалено.'))
    if action=='remove': await show_favorites(q.message,store,user['id'],0)

@router.callback_query(F.data.startswith('favorites'))
async def favorites(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    try: offset=max(0,int(q.data.split(':')[1])) if ':' in q.data else 0
    except ValueError: await q.answer(); return
    await q.answer(); await show_favorites(q.message,store,user['id'],offset)

async def show_favorites(message,store,user_id,offset):
    async with store.connect() as db:
        row=await (await db.execute('SELECT r.* FROM favorites f JOIN restaurants r ON r.id=f.restaurant_id WHERE f.user_id=? ORDER BY f.id DESC LIMIT 1 OFFSET ?',(user_id,offset))).fetchone()
    if not row:
        await message.answer('<b>Список пока пуст</b>\n\nЗдесь появятся сохранённые заведения.',reply_markup=keyboard([[('Tinder Mode','tinder'),('Find Restaurant','discover')],[('Главное меню','menu')]])); return
    buttons=keyboard([[('Подробнее',f'detail:{row["id"]}'),('Удалить',f'fav:remove:{row["id"]}')],[('←',f'favorites:{max(0,offset-1)}'),('Следующее →',f'favorites:{offset+1}')],[('Главное меню','menu')]])
    await card(message,row,buttons)

@router.callback_query(F.data.startswith('detail:'))
async def detail(q:CallbackQuery,store):
    if not await current_user(q,store): return
    try: rid=int(q.data.split(':')[1])
    except (ValueError,IndexError): await q.answer(); return
    async with store.connect() as db:
        row=await (await db.execute('SELECT * FROM restaurants WHERE id=?',(rid,))).fetchone()
    if not row: await q.answer('Заведение не найдено.',show_alert=True); return
    await q.answer(); await q.message.answer(text_card(row)+f"\n\nТелефон: {h(row['phone'])}\nСайт: {h(row['website'])}\nInstagram: {h(row['instagram'])}\nИсточник: {h(row['page_url'])}\nВремя работы: {h(row['working_hours'])}")

@router.callback_query(F.data == 'tinder')
async def tinder_start(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    session=await svc.begin_tinder(store,user['id']); await q.answer(); await show_tinder(q.message,store,user['id'],session)

async def show_tinder(message,store,user_id,session):
    row=await svc.next_tinder(store,user_id,session)
    if not row:
        await message.answer('<b>На сегодня всё</b>\n\nВы просмотрели все доступные заведения.',reply_markup=keyboard([[('Начать заново','tinder'),('Хочу сходить','favorites')],[('Главное меню','menu')]])); return
    buttons=keyboard([[('✕ Не нравится',Swipe(session=session,restaurant=row['id'],action='dislike').pack()),('✓ Нравится',Swipe(session=session,restaurant=row['id'],action='like').pack())],[('Подробнее',f'detail:{row["id"]}'),('Завершить',f'tend:{session}')]])
    await card(message,row,buttons,show_preference=False)

@router.callback_query(Swipe.filter())
async def swipe(q:CallbackQuery,callback_data:Swipe,store):
    user=await current_user(q,store)
    if not user: return
    accepted=await svc.tinder_action(store,user['id'],callback_data.session,callback_data.restaurant,callback_data.action)
    if not accepted: await q.answer('Эта карточка уже обработана.',show_alert=True); return
    await q.answer('Сохранено')
    try: await q.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await show_tinder(q.message,store,user['id'],callback_data.session)

@router.callback_query(F.data.startswith('tend:'))
async def end_tinder(q:CallbackQuery,store):
    user=await current_user(q,store)
    if not user: return
    try: session=int(q.data.split(':')[1])
    except (ValueError,IndexError): await q.answer(); return
    async with store.connect() as db:
        await db.execute("UPDATE tinder_sessions SET status='ended',ended_at=? WHERE id=? AND user_id=? AND status='active'",(svc.now(),session,user['id'])); await db.commit()
    try: await q.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await q.answer(); await q.message.answer('Tinder Mode завершён.',reply_markup=keyboard([[('Главное меню','menu')]]))
