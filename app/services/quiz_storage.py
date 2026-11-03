"""Persist only discovery FSM state; authentication data stays in memory."""
import json
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

class QuizStorage(MemoryStorage):
    def __init__(self, store):
        super().__init__(); self.store=store

    @staticmethod
    def key(key: StorageKey):
        return json.dumps([key.bot_id,key.chat_id,key.user_id,key.thread_id,key.business_connection_id,key.destiny],separators=(',',':'))

    async def get_state(self,key):
        state=await super().get_state(key)
        if state is not None: return state
        async with self.store.connect() as db:
            row=await (await db.execute('SELECT state,data FROM quiz_state WHERE state_key=?',(self.key(key),))).fetchone()
        if row:
            await super().set_state(key,row['state']); await super().set_data(key,json.loads(row['data']))
            return row['state']
        return None

    async def set_state(self,key,state=None):
        await super().set_state(key,state)
        value=await super().get_state(key)
        async with self.store.connect() as db:
            if value and value.startswith('Quiz:'):
                data=await super().get_data(key)
                data={k:data[k] for k in ('step','prefs','session','base_ids') if k in data}
                await db.execute("INSERT INTO quiz_state VALUES(?,?,?) ON CONFLICT(state_key) DO UPDATE SET state=excluded.state,data=excluded.data",(self.key(key),value,json.dumps(data,ensure_ascii=False)))
            else:
                await db.execute('DELETE FROM quiz_state WHERE state_key=?',(self.key(key),))
            await db.commit()

    async def get_data(self,key):
        await self.get_state(key)
        return await super().get_data(key)

    async def set_data(self,key,data):
        await super().set_data(key,data)
        state=await super().get_state(key)
        if state and state.startswith('Quiz:'):
            safe={k:data[k] for k in ('step','prefs','session','base_ids') if k in data}
            async with self.store.connect() as db:
                await db.execute('UPDATE quiz_state SET data=? WHERE state_key=?',(json.dumps(safe,ensure_ascii=False),self.key(key)))
                await db.commit()
