import json
import sqlite3
import pytest
from app.database.store import Store
from app.database.discovery_migration import migrate
from app.services.restaurant_import_service import import_data, parse_price

@pytest.mark.parametrize(('value','expected'),[('7500–13700 ₸',(7500,13700,10600)),('5 000–8 000 ₸',(5000,8000,6500)),('5000 ₸',(5000,5000,5000)),('от 5000 ₸',(5000,None,None)),('до 5000 ₸',(None,5000,None)),('',(None,None,None))])
def test_prices(value,expected):
    assert parse_price(value)==expected

@pytest.mark.asyncio
async def test_migration_import_and_reimport(tmp_path):
    db=tmp_path/'test.db'; store=Store(db); await store.initialize('initial-pass')
    await store.insert_restaurant('Existing','District','Cafe',5000)
    await store.insert_log(1,'old',recommended_restaurant_id=1)
    backup=migrate(db); assert backup
    record={'id':123,'site_id':'42','name':'Venue','source':'source','type':'Cafe','average_bill':'5000–8000 ₸','photos':['https://example.org/1','https://example.org/2'],'photo':'https://example.org/1','color_palette_hex':['#123456'],'page_url':'https://example.org','latitude':51,'longitude':71}
    source=tmp_path/'places.json'; source.write_text(json.dumps([record,record,{'name':''}]),encoding='utf8')
    first=import_data(source,db)
    assert (first['inserted'],first['duplicates'],first['rejected'],first['database_total'])==(1,1,1,2)
    second=import_data(source,db)
    assert second['inserted']==0 and second['unchanged']==1
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT * FROM restaurants WHERE site_id=?',('42',)).fetchone()
        assert json.loads(row['photos'])==record['photos'] and json.loads(row['color_palette_hex'])==['#123456']
        assert row['original_json_id']=='123' and row['district'] is None and row['price_midpoint']==6500
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert c.execute('SELECT recommended_restaurant_id FROM logs').fetchone()[0]==1
    record['name']='Changed'; source.write_text(json.dumps([record]),encoding='utf8')
    assert import_data(source,db)['updated']==1
