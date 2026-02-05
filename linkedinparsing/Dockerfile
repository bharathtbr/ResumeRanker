FROM public.ecr.aws/lambda/python:3.11

# Install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Set handler
CMD ["lambda_function.lambda_handler"]
