#!/bin/bash

# Deployment script for Resume Scoring Lambda Function

set -e

FUNCTION_NAME="resume-scoring-lambda"
REGION="us-east-1"
RUNTIME="python3.11"
HANDLER="lambda_function.lambda_handler"
ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT_ID:role/YOUR_LAMBDA_ROLE"
MEMORY_SIZE=1024
TIMEOUT=300

echo "Creating deployment package..."
rm -rf deployment
mkdir -p deployment

cp lambda_function.py deployment/

echo "Installing dependencies..."
pip install -r requirements.txt -t deployment/package/

cd deployment
if [ -d "package" ]; then
    cd package
    zip -r ../lambda_package.zip . > /dev/null
    cd ..
fi
zip -g lambda_package.zip lambda_function.py > /dev/null
cd ..

echo "Deployment package created: deployment/lambda_package.zip"

if aws lambda get-function --function-name $FUNCTION_NAME --region $REGION &> /dev/null; then
    echo "Updating existing Lambda function..."
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://deployment/lambda_package.zip \
        --region $REGION
    
    echo "Lambda function updated successfully!"
else
    echo "Creating new Lambda function..."
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $ROLE_ARN \
        --handler $HANDLER \
        --zip-file fileb://deployment/lambda_package.zip \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --region $REGION \
        --environment Variables="{
            DB_HOST=your-db-host,
            DB_NAME=your-db-name,
            DB_USER=your-db-user,
            DB_PASSWORD=your-db-password,
            DB_PORT=5432,
            AWS_REGION=$REGION,
            BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
        }"
    
    echo "Lambda function created successfully!"
fi

echo "Deployment completed successfully!"
