"""Generate reproducible synthetic sources, dated relative to today."""
import argparse
import json
import sqlite3
from datetime import date, timedelta
import pandas as pd
from app.db import runtime

def generate():
    directory = runtime() / 'source'
    directory.mkdir(exist_ok=True)
    day = lambda offset: (date.today() + timedelta(days=offset)).isoformat()
    suppliers = [{'supplier_id':'SUP-01','name':'Precision Metals'},
                 {'supplier_id':'SUP-02','name':'Circuit Works'}]
    inventory = [dict(zip(['sku','name','supplier_id','quantity','counted_quantity','reorder_point','unit_cost','opening_quantity','consumed_quantity'], row)) for row in [
        ('RM-001','Steel sheets','SUP-01',18,18,30,45,100,82),
        ('RM-002','Copper wire','SUP-02',0,0,20,12,80,80),
        ('FG-001','Control modules','SUP-02',150,146,40,85,200,50),
        ('RM-003','Aluminium rods','SUP-01',95,95,25,22,120,25)]]
    orders = [dict(zip(['po_id','sku','supplier_id','quantity','status','ordered_date','expected_date','delivered_date'], row)) for row in [
        ('PO-101','RM-001','SUP-01',100,'shipped',day(-10),day(-2),None),
        ('PO-102','RM-002','SUP-02',80,'pending',day(-5),day(2),None),
        ('PO-103','FG-001','SUP-02',50,'delivered',day(-20),day(-10),day(-9)),
        ('PO-104','RM-003','SUP-01',100,'delivered',day(-20),day(-12),day(-13))]]
    bundle = {'suppliers':suppliers,'inventory':inventory,'purchase_orders':orders}
    for table, records in bundle.items():
        pd.DataFrame(records).to_csv(directory / f'{table}.csv', index=False)
    with sqlite3.connect(directory / 'upstream.db') as conn:
        for table, records in bundle.items():
            pd.DataFrame(records).to_sql(table, conn, if_exists='replace', index=False)
    (directory / 'bundle.json').write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    return directory

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(f'Demo source files created in {generate()}')
