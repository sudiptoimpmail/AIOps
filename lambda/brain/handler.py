import json, time, os, uuid, boto3
from datetime import datetime, timedelta

bedrock  = boto3.client("bedrock-runtime", region_name="us-east-2")
cw       = boto3.client("cloudwatch",        region_name="us-east-2")
dynamodb = boto3.resource("dynamodb")
sns      = boto3.client("sns",                region_name="us-east-2")
lam      = boto3.client("lambda",             region_name="us-east-2")

TABLE     = os.environ["INCIDENT_TABLE"]
TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]



# ── Step 1: Pull last 10 min of metrics ───────────────────────────
def get_current_metrics() -> dict:
    end   = datetime.utcnow()
    start = end - timedelta(minutes=2)
    result = {}
    for metric in ["ErrorRate", "Latency", "RequestCount"]:
        resp = cw.get_metric_statistics(
            Namespace="AIOpsDemo", MetricName=metric,
            Dimensions=[{"Name": "Service", "Value": "order-processor"}],
            StartTime=start, EndTime=end,
            Period=60, Statistics=["Average"]
        )
        pts = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"])
        result[metric] = round(pts[-1]["Average"], 2) if pts else 0
    return result


# ── Step 2: Ask Claude what it means ──────────────────────────────
def classify_with_claude(alarm_name: str, metrics: dict) -> dict:
    prompt = f"""You are an SRE analyzing a CloudWatch alarm.

Alarm: {alarm_name}
Current metrics (last 10 minutes):
  ErrorRate:    {metrics.get('ErrorRate', 0):.1f}%
  Latency:      {metrics.get('Latency', 0):.0f}ms
  RequestCount: {metrics.get('RequestCount', 0):.0f} requests/min

Classify this situation. Respond ONLY with valid JSON, no other text:
{{
  "classification": "noise" or "incident" or "outage",
  "severity": "low" or "medium" or "high" or "critical",
  "probable_cause": "one sentence",
  "recommended_playbook": "restart_app" or "scale_up" or "escalate",
  "auto_remediate": true or false,
  "summary": "two sentence plain-English summary for an engineer"
}}"""

    resp = bedrock.invoke_model(
        modelId="arn:aws:bedrock:us-east-2:160631388468:application-inference-profile/6bdlb448as3d",
        body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "temperature": 0,   # IMPORTANT
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    })
    )

    raw = resp["body"].read().decode("utf-8")

    print(f"Claude raw response: {raw}")
    text = json.loads(raw)["content"][0]["text"]
    return text


# ── Step 3: Execute playbook ──────────────────────────────────────
def execute_playbook(playbook: str) -> str:
    if playbook == "restart_app":
        # In a real system: ecs.update_service(forceNewDeployment=True)
        # For this lab: invoke sample app in normal mode to "heal" it
        
        return "Triggered app restart — invoking sample app in normal mode"
    elif playbook == "scale_up":
        # In a real system: autoscaling.set_desired_capacity(...)
        return "Scale-up playbook noted — no ASG configured in lab"
    else:
        return "Escalation required — no auto-remediation taken"


# ── Step 4: Verify alarm cleared ─────────────────────────────────
def check_alarm_state(alarm_name: str) -> str:
    resp   = cw.describe_alarms(AlarmNames=[alarm_name])
    alarms = resp["MetricAlarms"]
    return alarms[0]["StateValue"] if alarms else "UNKNOWN"


# ── Main handler ──────────────────────────────────────────────────
def lambda_handler(event, context):
    # Parse SNS message from CloudWatch alarm
    msg        = json.loads(event["Records"][0]["Sns"]["Message"])
    alarm_name = msg.get("AlarmName", "unknown")
    new_state  = msg.get("NewStateValue", "ALARM")
    incident_id = str(uuid.uuid4())[:8]

    # Only run when alarm transitions TO alarm state
    if new_state != "ALARM":
        print(f"Alarm {alarm_name} → {new_state}. No action needed.")
        return

    print(f"🚨 Incident {incident_id}: {alarm_name} in ALARM")
    t_start = time.time()

    # 1. Get context
    metrics = get_current_metrics()
    print(f"📊 Metrics: {metrics}")

    # 2. Classify
    analysis = classify_with_claude(alarm_name, metrics)
    print(f"🧠 Claude says: {analysis}")

    # 3. Act
    action_taken = "none"
    if analysis.get("auto_remediate") and analysis["classification"] != "noise":
        action_taken = execute_playbook(analysis["recommended_playbook"])
        print(f"⚡ Action: {action_taken}")
        time.sleep(60)  # wait for remediation to take effect

    # 4. Verify
    final_state = check_alarm_state(alarm_name)
    recovered   = final_state == "OK"
    mttr_secs   = round(time.time() - t_start)
    print(f"✅ Alarm state after remediation: {final_state}. MTTR: {mttr_secs}s")

    # 5. Store in DynamoDB
    dynamodb.Table(TABLE).put_item(Item={
        "incident_id":  incident_id,
        "alarm_name":   alarm_name,
        "timestamp":    datetime.utcnow().isoformat(),
        "classification": analysis["classification"],
        "severity":     analysis["severity"],
        "probable_cause": analysis["probable_cause"],
        "playbook":     analysis["recommended_playbook"],
        "action_taken": action_taken,
        "recovered":    recovered,
        "mttr_seconds": mttr_secs,
    })

    # 6. Send incident report
    status_icon = "✅" if recovered else "❌"
    report = f"""
AIOps Incident Report — {incident_id}
{'='*45}
Alarm:          {alarm_name}
Classification: {analysis['classification'].upper()} ({analysis['severity']} severity)
Probable cause: {analysis['probable_cause']}

AI Summary:
{analysis['summary']}

Action taken:  {action_taken}
Recovered:     {status_icon} {final_state}
MTTR:          {mttr_secs} seconds

Metrics at time of incident:
  Error rate:  {metrics.get('ErrorRate', 0):.1f}%
  Latency:     {metrics.get('Latency', 0):.0f}ms
  Req/min:     {metrics.get('RequestCount', 0):.0f}
"""
    sns.publish(TopicArn=TOPIC_ARN,
                Subject=f"AIOps Report: {analysis['classification'].upper()} — {alarm_name}",
                Message=report)
    print(report)
    return {"incident_id": incident_id, "classification": analysis["classification"], "recovered": recovered}