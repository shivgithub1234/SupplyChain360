"""Pure rule evaluation followed by stateful alert reconciliation."""
from datetime import datetime, timedelta
from app.db import connect

def evaluate(conn, today):
    found = []
    def add(rule, entity, severity, message):
        found.append((f'{rule}:{entity}',rule,entity,severity,message))
    for row in conn.execute('SELECT * FROM inventory'):
        if row['quantity'] <= row['reorder_point']:
            add('low_stock',row['sku'],'critical' if row['quantity']==0 else 'warning',f"{row['name']}: {row['quantity']} available; reorder point {row['reorder_point']}")
        if row['quantity'] != row['counted_quantity']:
            add('inventory_discrepancy',row['sku'],'warning',f"{row['name']}: system {row['quantity']}, physical count {row['counted_quantity']}")
    for row in conn.execute('SELECT * FROM purchase_orders'):
        if row['status'] != 'delivered' and row['expected_date'] < today.isoformat():
            add('delayed_shipment',row['po_id'],'critical',f"{row['po_id']} overdue since {row['expected_date']}")
        if row['status'] == 'pending' and row['ordered_date'] <= (today-timedelta(days=3)).isoformat():
            add('pending_order',row['po_id'],'warning',f"{row['po_id']} pending for at least 3 days")
    return found

def reconcile(now):
    timestamp = now.isoformat()
    with connect() as conn:
        found = evaluate(conn, now.date())
        prior = {r['alert_key']:dict(r) for r in conn.execute('SELECT * FROM alerts')}
        conn.execute('UPDATE alerts SET active=0')
        for key, rule, entity, severity, message in found:
            old = prior.get(key)
            new = not old or not old['active']
            first = timestamp if new else old['first_seen']
            escalated = 0 if new else old['escalated']
            conn.execute('''INSERT INTO alerts VALUES (?,?,?,?,?,1,?,?,?)
                ON CONFLICT(alert_key) DO UPDATE SET severity=excluded.severity,
                message=excluded.message,active=1,first_seen=excluded.first_seen,
                last_seen=excluded.last_seen,escalated=excluded.escalated''',
                (key,rule,entity,severity,message,first,timestamp,escalated))
            if new:
                conn.execute('INSERT INTO notifications(created_at,kind,message) VALUES (?,?,?)',(timestamp,'alert',message))
            elif not escalated and now-datetime.fromisoformat(first) >= timedelta(hours=24):
                conn.execute('UPDATE alerts SET escalated=1 WHERE alert_key=?',(key,))
                conn.execute('INSERT INTO notifications(created_at,kind,message) VALUES (?,?,?)',(timestamp,'escalation',message))
        active = {a[0] for a in found}
        for key, old in prior.items():
            if old['active'] and key not in active:
                conn.execute('INSERT INTO notifications(created_at,kind,message) VALUES (?,?,?)',(timestamp,'resolved',old['message']))
        conn.execute('INSERT INTO audit(created_at,action,detail) VALUES (?,?,?)',(timestamp,'rules_evaluated',f'{len(found)} active exceptions'))
    return len(found)
