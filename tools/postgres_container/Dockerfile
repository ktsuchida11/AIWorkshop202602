FROM --platform=arm64 postgres:17.7

RUN apt-get update && \
    apt-get install -y git make gcc postgresql-server-dev-17

RUN cd /tmp && \
    git clone --branch v0.8.1 https://github.com/pgvector/pgvector.git && \
    cd pgvector && \
    make && \
    make install && \
    cd ../ && rm -rf pgvector
