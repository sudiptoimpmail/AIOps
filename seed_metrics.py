#!/usr/bin/env python3
"""
seed_metrics.py — push AIOpsDemo metrics to CloudWatch from your Mac.
Usage:
  python seed_metrics.py          # normal mode  (ErrorRate ~5%)
  python seed_metrics.py spike    # spike mode   (ErrorRate ~60%)
  python seed_metrics.py          # run normal first, then spike to trigger alarm
"""
import boto3, random, time, sys
from datetime import datetime, timezone

cw     = boto3.client("cloudwatch", region_name="us-east-2")
mode   = sys.argv[1] if len(sys.argv) > 1 else "normal"
runs   = 5 if mode == "spike" else 15

error_rate = 0.60 if mode == "spike" else 0.05
latency_fn = lambda: random.randint(400, 900) if mode == "spike" else random.randint(20, 80)

print(f"Pushing {runs} data points in [{mode}] mode  (ErrorRate ~{error_rate*100:.0f}%)")

for i in range(runs):
    latency = latency_fn()
    err_pct = error_rate * 100 + random.uniform(-3, 3)  # small jitter

    cw.put_metric_data(
        Namespace="AIOpsDemo",
        MetricData=[
            {"MetricName": "ErrorRate",
             "Dimensions": [{"Name": "Service", "Value": "order-processor"}],
             "Value": err_pct, "Unit": "Percent",
             "Timestamp": datetime.now(tz=timezone.utc)},
            {"MetricName": "Latency",
             "Dimensions": [{"Name": "Service", "Value": "order-processor"}],
             "Value": latency, "Unit": "Milliseconds",
             "Timestamp": datetime.now(tz=timezone.utc)},
            {"MetricName": "RequestCount",
             "Dimensions": [{"Name": "Service", "Value": "order-processor"}],
             "Value": 1, "Unit": "Count",
             "Timestamp": datetime.now(tz=timezone.utc)},
        ]
    )
    print(f"  [{i+1:2}/{runs}] ErrorRate={err_pct:.1f}%  Latency={latency}ms")
    time.sleep(1)

print(f"\n✅ Done. Check CloudWatch → Metrics → AIOpsDemo in ~30 seconds.")
if mode == "spike":
    print("   Alarm should fire within 60s — watch CloudWatch → Alarms.")
