"""SQL KPIs. Undefined ratios are null, rather than misleading zeroes."""
from app.db import connect

def kpis():
    with connect() as conn:
        inventory = dict(conn.execute('''SELECT COUNT(*) sku_count,
            100.0*SUM(quantity>0)/NULLIF(COUNT(*),0) stock_availability_pct,
            SUM(quantity*unit_cost) inventory_value,
            SUM(consumed_quantity*unit_cost)/NULLIF(SUM((opening_quantity+quantity)*unit_cost/2.0),0) inventory_turnover
            FROM inventory''').fetchone())
        delivery = dict(conn.execute('''SELECT
            100.0*SUM(delivered_date<=expected_date)/NULLIF(COUNT(*),0) on_time_delivery_pct
            FROM purchase_orders WHERE status='delivered' ''').fetchone())
        runs = dict(conn.execute('''SELECT COUNT(*) total_runs,
            AVG(duration_ms) avg_processing_ms,
            100.0*SUM(status='success')/NULLIF(COUNT(*),0) workflow_completion_pct,
            100.0*SUM(sla_met=1)/NULLIF(COUNT(*),0) sla_adherence_pct
            FROM runs WHERE status!='running' ''').fetchone())
        active = conn.execute('SELECT COUNT(*) FROM alerts WHERE active=1').fetchone()[0]
        entities = conn.execute('''SELECT COUNT(*) FROM (
            SELECT 'sku:'||entity FROM alerts WHERE active=1 AND rule IN ('low_stock','inventory_discrepancy')
            UNION SELECT 'po:'||entity FROM alerts WHERE active=1 AND rule IN ('delayed_shipment','pending_order'))''').fetchone()[0]
        total = conn.execute('SELECT (SELECT COUNT(*) FROM inventory)+(SELECT COUNT(*) FROM purchase_orders)').fetchone()[0]
        suppliers = [dict(r) for r in conn.execute('''SELECT s.supplier_id,s.name,
            COUNT(p.po_id) delivered_orders,
            100.0*SUM(p.delivered_date<=p.expected_date)/NULLIF(COUNT(p.po_id),0) on_time_pct
            FROM suppliers s LEFT JOIN purchase_orders p ON s.supplier_id=p.supplier_id AND p.status='delivered'
            GROUP BY s.supplier_id,s.name''')]
    return {**inventory, **delivery, **runs, 'active_exceptions':active,
            'exception_rate_pct':100*entities/total if total else None,'suppliers':suppliers}
