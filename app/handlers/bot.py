import asyncio
import html
import logging
import sqlite3
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.services.security import hasher, valid_age, valid_password, valid_username, verify

router = Router()
log = logging.getLogger(__name__)

class Flow(StatesGroup):
    username = State()
    password = State()
    age = State()
    confirm = State()
    login_name = State()
    login_password = State()
    current_password = State()
    new_password = State()
    confirm_password = State()
    delete_confirm = State()

def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data) for label,data in row] for row in rows])

GUEST = kb([('Войти','login')],[('Регистрация','register')],[('Подробнее →','about')])
BACK = kb([('← Назад','menu')])
CANCEL = kb([('Отмена','cancel')])
WELCOME = '<b>Welcome to Your Restaurant Here</b>\n\nНайди идеальное заведение в Астане.\n\nРестораны, кафе и новые места — в одном сервисе.\n\n────────────────'
FINISH_WELCOME = '<b>Welcome to Your Restaurant Here</b>\n\nНайди идеальное заведение в Астане.\n\nМы поможем выбрать подходящее место для следующего визита.\n\n────────────────'
ABOUT = '<b>О Your Restaurant Here</b>\n\nПоиск подходящего заведения не должен занимать много времени.\n\nМы создаём платформу, которая объединяет поиск кафе и ресторанов, информацию о ценах, местоположении и персональные рекомендации.\n\nВыбирай район, указывай бюджет и находи места, которые подходят именно тебе.\n\nВ будущем платформа также предложит поиск по блюдам, специальные предложения и систему бонусов.'

async def edit(q, text, keyboard):
    try:
        await q.message.edit_text(text, reply_markup=keyboard)
    except Exception as exc:
        if 'message is not modified' not in str(exc).lower():
            log.warning('Could not edit message: %s', type(exc).__name__)
            await q.message.answer(text,reply_markup=keyboard)
    await q.answer()

async def menu_text(user):
    if not user:
        return WELCOME, GUEST
    name = html.escape(user['username'])
    if user['role'] == 'admin':
        return f'<b>Your Restaurant Here</b>\n<b>Панель администратора</b>\n\nВы вошли как {name}.\n\n────────────────', kb([('Пользователи','admin:users:0')],[('Рестораны','admin:restaurants')],[('История действий','admin:logs')],[('Статистика','admin:stats')],[('Аналитика','analytics:all')],[('Find Restaurant','discover'),('Tinder Mode','tinder')],[('Хочу сходить','favorites')],[('Аккаунт','profile')],[('Завершить','finish')])
    return f'<b>Your Restaurant Here</b>\n\nДобро пожаловать, {name}.\n\nЧто хотите сделать?', kb([('Find Restaurant','discover')],[('Tinder Mode','tinder')],[('Хочу сходить','favorites')],[('Аккаунт','profile')],[('О проекте','about')],[('Завершить','finish')])

async def show_menu(q, state, store):
    user = await store.get_user(q.from_user.id)
    await state.clear()
    text, keyboard = await menu_text(user)
    await edit(q, text, keyboard)

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, store):
    if message.chat.type != 'private':
        return
    if (await state.get_state() or '').startswith('Quiz:') and await store.get_user(message.from_user.id):
        await message.answer('<b>Незавершённый поиск</b>\n\nПродолжить анкету с сохранённого шага?',reply_markup=kb([('Продолжить →','quiz:resume')],[('Главное меню','menu')])); return
    await state.clear()
    user = await store.get_user(message.from_user.id)
    text, keyboard = await menu_text(user)
    await message.answer(text, reply_markup=keyboard)

def account_screen(user):
    if not user:
        return '<b>Аккаунт</b>\n\nДля управления профилем необходимо войти в систему.', kb([('Войти','login')],[('Регистрация','register')],[('← Назад','menu')])
    age = user['age'] if user['age'] is not None else 'не указан'
    role = 'администратор' if user['role'] == 'admin' else 'пользователь'
    buttons = [[('Выйти','logout')],[('Сменить пароль','password:change')]]
    if user['role'] == 'user': buttons.append([('Удалить аккаунт','delete:ask')])
    buttons.append([('← Назад','menu')])
    return f"<b>Your Restaurant Here</b>\n\n<b>Аккаунт</b>\n\n────────────────\n\nИмя: {html.escape(user['username'])}\nРоль: {role}\nВозраст: {age}\n\nУправление профилем:", kb(*buttons)

@router.message(Command('account'))
async def account_command(message: Message, state: FSMContext, store):
    if message.chat.type != 'private': return
    await state.clear()
    text, keyboard = account_screen(await store.get_user(message.from_user.id))
    await message.answer(text, reply_markup=keyboard)

@router.message(Command('finish'))
async def finish_command(message: Message, state: FSMContext, store):
    if message.chat.type != 'private': return
    await store.logout(message.from_user.id)
    await state.clear()
    await message.answer(FINISH_WELCOME, reply_markup=GUEST)

@router.message(Command('help'))
async def help_command(message: Message, state: FSMContext):
    if message.chat.type != 'private': return
    await message.answer('<b>Помощь</b>\n\n/account — управление аккаунтом\n/finish — завершить сеанс\n/start — главная', reply_markup=BACK)

@router.callback_query()
async def callback(q: CallbackQuery, state: FSMContext, store, notifications):
    if not q.message or q.message.chat.type != 'private':
        await q.answer(); return
    action = q.data or ''
    user = await store.get_user(q.from_user.id)
    current = await state.get_state()
    if action in ('menu','cancel'):
        await show_menu(q,state,store); return
    if action == 'logout':
        await store.logout(q.from_user.id); await state.clear(); await edit(q,'<b>Вы вышли из аккаунта</b>\n\nСессия успешно завершена.',kb([('На главную →','menu')])); return
    if action == 'finish':
        await store.logout(q.from_user.id); await state.clear(); await edit(q,FINISH_WELCOME,GUEST); return
    if action == 'about':
        await edit(q,ABOUT,BACK); return
    if action in ('login','register'):
        if user:
            await show_menu(q,state,store); return
        await state.clear()
        await state.set_state(Flow.username if action == 'register' else Flow.login_name)
        await edit(q, '<b>Регистрация</b>\n\nШаг 1 из 3\n\nПридумайте имя пользователя.\nИмя должно быть уникальным.\n\nНапример: matvei228' if action == 'register' else '<b>Вход</b>\n\nВведите имя пользователя.', CANCEL); return
    if action == 'reg:back' and current == Flow.confirm.state:
        await state.set_state(Flow.age); await edit(q,'<b>Регистрация</b>\n\nШаг 3 из 3\n\nУкажите ваш возраст.',CANCEL); return
    if action == 'reg:confirm':
        if current != Flow.confirm.state or user:
            await q.answer('Этот шаг уже завершён или устарел.',show_alert=True); return
        data = await state.get_data()
        try:
            await store.register(data['username'], data['password_hash'], data['age'], q.from_user.id)
        except sqlite3.IntegrityError:
            await state.clear(); await edit(q,'Не удалось создать аккаунт: имя или Telegram уже связаны с аккаунтом. Войдите или выберите другое имя.',GUEST); return
        except Exception:
            log.exception('Registration failed')
            await q.answer('Не удалось сохранить данные. Попробуйте ещё раз.',show_alert=True); return
        await state.clear()
        await edit(q, f"<b>Регистрация завершена</b>\n\n✓ Аккаунт успешно создан.\n\nИмя: {html.escape(data['username'])}\nВозраст: {data['age']}\n\nДобро пожаловать в Your Restaurant Here.",kb([('Перейти в меню →','menu')]))
        asyncio.create_task(notifications.dispatch()); return
    if action == 'profile':
        await state.clear()
        text, keyboard = account_screen(user)
        await edit(q,text,keyboard); return
    if not user:
        await q.answer('Сначала войдите в аккаунт.',show_alert=True); return
    if action == 'find':
        await edit(q,'Начните поиск в главном меню.',kb([('Find Restaurant','discover'),('← Назад','menu')])); return
    if action == 'password:change':
        await state.clear(); await state.set_state(Flow.current_password)
        await edit(q,'<b>Смена пароля</b>\n\nВведите текущий пароль.',kb([('Отмена','profile')])); return
    if action == 'delete:ask' and user['role'] == 'user':
        await state.set_state(Flow.delete_confirm)
        await edit(q,'<b>Удаление аккаунта</b>\n\nУдалить аккаунт? Это действие нельзя отменить. Если с аккаунтом связана история действий, удаление невозможно без помощи администратора.',kb([('✓ Удалить','delete:confirm')],[('← Назад','profile')])); return
    if action == 'delete:confirm' and user['role'] == 'user':
        if current != Flow.delete_confirm.state:
            await q.answer('Сначала подтвердите удаление в профиле.', show_alert=True); return
        if await store.delete_account(q.from_user.id):
            await state.clear(); await edit(q,'Аккаунт удалён.',GUEST)
        else:
            await edit(q,'Не удалось удалить аккаунт: сохранена история действий. Обратитесь к администратору.',BACK)
        return
    if action.startswith('admin:'):
        if user['role'] != 'admin':
            await q.answer('Доступ запрещён.',show_alert=True); return
        stats = await store.stats()
        if action.startswith('admin:users:'):
            try: page = max(0, min(int(action.split(':')[2]), 100000))
            except (ValueError, IndexError): await q.answer(); return
            users = await store.users_page(page*10)
            lines = '\n'.join(f"• {html.escape(u['username'])} — {'администратор' if u['role']=='admin' else 'пользователь'}" for u in users) or 'Нет пользователей на этой странице.'
            buttons = []
            if page: buttons.append(('←',f'admin:users:{page-1}'))
            if (page+1)*10 < stats['users']: buttons.append(('→',f'admin:users:{page+1}'))
            rows = ([buttons] if buttons else []) + [[('← Назад','menu')]]
            await edit(q,f"<b>Пользователи</b>\n\nВсего: {stats['users']}\nАдминистраторы: {stats['admins']}\nПользователи: {stats['users']-stats['admins']}\n\n{lines}",kb(*rows)); return
        if action == 'admin:restaurants': text = f"<b>Рестораны</b>\n\nВсего записей: {stats['restaurants']}" + ('\nБаза пока пуста.' if not stats['restaurants'] else '')
        elif action == 'admin:logs':
            logs = await store.recent_logs()
            lines = '\n'.join(f"• ID {row['user_id']} — {html.escape(row['action'])} — {html.escape(row['created_at'])}" for row in logs) or 'Событий пока нет.'
            text = f"<b>История действий</b>\n\nВсего: {stats['logs']}\n\n{lines}"
        elif action == 'admin:stats': text = f"<b>Статистика платформы</b>\n\nПользователи: {stats['users']}\nАдминистраторы: {stats['admins']}\nРестораны: {stats['restaurants']}\nСобытия: {stats['logs']}"
        else: await q.answer(); return
        await edit(q,text,BACK); return
    await q.answer()

@router.message(StateFilter(Flow.username, Flow.password, Flow.age, Flow.login_name, Flow.login_password, Flow.current_password, Flow.new_password, Flow.confirm_password))
async def input_step(message: Message, state: FSMContext, store, notifications):
    if message.chat.type != 'private': return
    current = await state.get_state()
    value = message.text
    if current in (Flow.password.state,Flow.login_password.state,Flow.current_password.state,Flow.new_password.state,Flow.confirm_password.state):
        try: await message.delete()
        except Exception: log.info('Could not delete password message')
    if value is None:
        await message.answer('Пожалуйста, отправьте текст.',reply_markup=CANCEL); return
    if current == Flow.username.state:
        if not valid_username(value):
            await message.answer('Имя должно содержать 3–32 латинские буквы, цифры или подчёркивания и не состоять только из цифр. Выберите другое имя.',reply_markup=CANCEL); return
        if await store.username_exists(value):
            await message.answer('Это имя уже занято.\nПопробуйте другое.',reply_markup=CANCEL); return
        await state.update_data(username=value); await state.set_state(Flow.password)
        await message.answer('<b>Регистрация</b>\n\nШаг 2 из 3\n\nПридумайте пароль от 8 до 128 символов.',reply_markup=CANCEL)
    elif current == Flow.password.state:
        if not valid_password(value): await message.answer('Пароль должен содержать от 8 до 128 символов.',reply_markup=CANCEL); return
        encoded = await asyncio.to_thread(hasher.hash,value)
        await state.update_data(password_hash=encoded); await state.set_state(Flow.age)
        await message.answer('<b>Регистрация</b>\n\nШаг 3 из 3\n\nУкажите ваш возраст.',reply_markup=CANCEL)
    elif current == Flow.age.state:
        if not valid_age(value): await message.answer('Введите целое число от 13 до 100.',reply_markup=CANCEL); return
        await state.update_data(age=int(value)); data = await state.get_data(); await state.set_state(Flow.confirm)
        await message.answer(f"<b>Подтверждение регистрации</b>\n\nИмя: {html.escape(data['username'])}\nВозраст: {data['age']}\n\nПароль: установлен\n\nПродолжая, вы соглашаетесь на хранение этих данных для работы профиля. Данные можно удалить через настройки профиля.",reply_markup=kb([('✓ Создать аккаунт','reg:confirm')],[('← Назад','reg:back')],[('Отмена','cancel')]))
    elif current == Flow.login_name.state:
        await state.update_data(username=value); await state.set_state(Flow.login_password); await message.answer('<b>Вход</b>\n\nВведите пароль.',reply_markup=CANCEL)
    elif current == Flow.login_password.state:
        data = await state.get_data(); result = await store.login(data['username'],value,message.from_user.id)
        if result in ('invalid','locked','linked','active'):
            await state.clear()
            text = {'invalid':'Неверное имя пользователя или пароль.','locked':'Слишком много попыток. Повторите вход через 5 минут.','linked':'Аккаунт уже связан с другим Telegram. Для восстановления обратитесь к администратору.','active':'Сначала выйдите из текущего аккаунта.'}[result]
            await message.answer(text,reply_markup=GUEST); return
        await state.clear(); user = await store.get_user(message.from_user.id)
        text, keyboard = await menu_text(user); await message.answer(text,reply_markup=keyboard)
        asyncio.create_task(notifications.dispatch())
    elif current == Flow.current_password.state:
        result = await store.verify_current_password(message.from_user.id,value)
        if result in ('invalid','locked','unauthenticated'):
            if result != 'invalid': await state.clear()
            await message.answer({'invalid':'Неверный текущий пароль. Попробуйте ещё раз.','locked':'Слишком много попыток. Повторите через 5 минут.','unauthenticated':'Сначала войдите в аккаунт.'}[result],reply_markup=kb([('← К аккаунту','profile')])); return
        await state.update_data(expected_hash=result); await state.set_state(Flow.new_password)
        await message.answer('Введите новый пароль от 8 до 128 символов.',reply_markup=kb([('Отмена','profile')]))
    elif current == Flow.new_password.state:
        if not await store.get_user(message.from_user.id): await state.clear(); await message.answer(WELCOME,reply_markup=GUEST); return
        if not valid_password(value): await message.answer('Пароль должен содержать от 8 до 128 символов.',reply_markup=kb([('Отмена','profile')])); return
        await state.update_data(new_hash=await asyncio.to_thread(hasher.hash,value)); await state.set_state(Flow.confirm_password)
        await message.answer('Повторите новый пароль.',reply_markup=kb([('Отмена','profile')]))
    elif current == Flow.confirm_password.state:
        data = await state.get_data()
        if not verify(data['new_hash'],value):
            await state.set_state(Flow.new_password); await message.answer('Пароли не совпадают. Введите новый пароль ещё раз.',reply_markup=kb([('Отмена','profile')])); return
        try:
            changed = await store.update_password_hash(message.from_user.id,data['expected_hash'],data['new_hash'])
        except Exception:
            log.exception('Password update failed'); await message.answer('Не удалось сохранить пароль. Попробуйте ещё раз.',reply_markup=kb([('Отмена','profile')])); return
        await state.clear()
        if not changed: await message.answer('Сессия или пароль изменились. Начните заново.',reply_markup=kb([('← К аккаунту','profile')])); return
        await message.answer('<b>Пароль изменён</b>\n\n✓ Новый пароль успешно сохранён.',reply_markup=kb([('← К аккаунту','profile')]))


