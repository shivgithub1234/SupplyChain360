import argparse
import json
import time
from app.db import initialize, runtime
from app.demo import generate
from app.workflow import configure_logging, run_pipeline

def main():
    parser = argparse.ArgumentParser(description='SupplyChain360 workflow runner')
    parser.add_argument('command',choices=['demo','run','schedule'])
    parser.add_argument('--source',choices=['csv','sqlite','api'],default='csv')
    parser.add_argument('--location',help='CSV directory, SQLite file, or JSON API URL')
    parser.add_argument('--interval',type=int,default=300,help='Seconds after each completed run')
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('interval must be positive')
    if args.source != 'csv' and not args.location:
        parser.error('--location is required for sqlite and api')
    initialize()
    configure_logging()
    if args.command == 'demo':
        generate()
    while True:
        try:
            print(json.dumps(run_pipeline(args.source,args.location),indent=2),flush=True)
        except Exception as exc:
            print(f'Workflow failed: {exc}',flush=True)
            if args.command != 'schedule':
                raise SystemExit(1)
        if args.command != 'schedule':
            break
        time.sleep(args.interval)

if __name__ == '__main__':
    main()
