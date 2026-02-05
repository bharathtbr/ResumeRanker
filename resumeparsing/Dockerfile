FROM public.ecr.aws/lambda/python:3.11

RUN yum install -y zip && yum clean all
WORKDIR /opt

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel && \
    pip install --only-binary=:all: -r requirements.txt -t /opt/python && \
    find /opt/python -type d -name "__pycache__" -exec rm -rf {} + && \
    find /opt/python -type f -name "*.pyc" -delete && \
    rm -rf /root/.cache

RUN cd /opt && zip -r9 /opt/lambda-layer.zip python

CMD ["bash", "-c", "cp /opt/lambda-layer.zip /out/lambda-layer.zip"]
