import argparse
import json
import sys
from pathlib import Path
from app.database.discovery_migration import migrate
from app.services.restaurant_import_service import import_data

ROOT = Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description='Импорт заведений в существующую базу')
    parser.add_argument('json_path',nargs='?',default=ROOT/'app/database/astana_places.json',type=Path)
    parser.add_argument('--database',default=ROOT/'perfect_restaurant.db',type=Path)
    args=parser.parse_args()
    try:
        # Validate the JSON before changing the database.
        data=json.loads(args.json_path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,list): raise ValueError('JSON должен содержать массив')
        backup=migrate(args.database)
        report=import_data(args.json_path,args.database)
    except (OSError,ValueError) as e:
        print(f'Ошибка импорта: {e}',file=sys.stderr); return 1
    print(json.dumps({'backup':backup,**report},ensure_ascii=False,indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
