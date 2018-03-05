FROM tiangolo/uwsgi-nginx-flask:python3.6

RUN pip install git+https://github.com/johejo/aiosphttp.git

COPY ./app /app