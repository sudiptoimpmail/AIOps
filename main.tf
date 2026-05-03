############################
# SNS ALERTS
############################

resource "aws_sns_topic" "alerts" {
  name = "aiops-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "sudipto.impmail@gmail.com"
}

############################
# CLOUDWATCH ALARM
############################

resource "aws_cloudwatch_metric_alarm" "error_rate" {
  alarm_name          = "aiops-error-rate-alarm"
  namespace           = "AIOpsDemo"
  metric_name         = "ErrorRate"

  dimensions = {
    Service = "order-processor"
  }

  statistic           = "Average"
  period              = 60
  evaluation_periods  = 1
  threshold           = 30
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

############################
# DYNAMODB - INCIDENTS
############################

resource "aws_dynamodb_table" "incidents" {
  name         = "aiops-incidents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }
}

############################
# IAM ROLE FOR BRAIN LAMBDA
############################

resource "aws_iam_role" "brain_role" {
  name = "aiops-brain-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "brain_policy_attachment" {
  role       = aws_iam_role.brain_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "brain_inline_policy" {
  name = "aiops-brain-permissions"
  role = aws_iam_role.brain_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      {
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:DescribeAlarms"
        ]
        Resource = "*"
      },

      {
        Effect = "Allow"
        Action = "bedrock:InvokeModel"
        Resource = "*"
      },

      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:Scan"
        ]
        Resource = aws_dynamodb_table.incidents.arn
      },

      {
        Effect = "Allow"
        Action = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

############################
# LAMBDA - BRAIN
############################

data "archive_file" "brain_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda/brain"
  output_path = "${path.module}/lambda_zips/aiops_brain.zip"
}

resource "aws_lambda_function" "brain" {
  function_name = "aiops-brain"

  filename         = data.archive_file.brain_zip.output_path
  source_code_hash = data.archive_file.brain_zip.output_base64sha256

  handler = "handler.lambda_handler"
  runtime = "python3.12"
  role    = aws_iam_role.brain_role.arn

  timeout     = 180
  memory_size = 512

  environment {
    variables = {
      INCIDENT_TABLE = aws_dynamodb_table.incidents.name
      SNS_TOPIC_ARN  = aws_sns_topic.alerts.arn
    }
  }
}

############################
# SNS -> LAMBDA PERMISSION
############################

resource "aws_lambda_permission" "sns_invoke_brain" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.brain.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_sns_topic_subscription" "brain_subscription" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.brain.arn
}

############################
# CLOUDWATCH LOG GROUP
############################

resource "aws_cloudwatch_log_group" "brain_logs" {
  name              = "/aws/lambda/aiops-brain"
  retention_in_days = 7
}