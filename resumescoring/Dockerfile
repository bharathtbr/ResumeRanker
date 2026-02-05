FROM public.ecr.aws/lambda/python:3.11

WORKDIR /var/task

COPY requirements.txt .

# Install zip utility and dependencies
RUN yum install -y zip \
    && pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt -t .

COPY . .

RUN zip -r /tmp/deployment-package.zip .
